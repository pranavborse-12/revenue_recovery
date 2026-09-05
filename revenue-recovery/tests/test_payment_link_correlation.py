"""
Tests for the Payment-Link correlation fallback (resolve_via_payment_link
+ resolve_unmatched_capture). Self-contained in-memory SQLite, same
pattern as test_phase3_customer_recovery.py.

Covers the 7 scenarios from the correlation-fix task:
  1. Existing same-order retry still works (regression, no change)
  2. Payment Link retry (different order) now resolves correctly
  3. Duplicate captured webhook stays idempotent
  4. Captured payment with no matching recovery is left alone
  5. Razorpay API failure during fallback -> retry, not false-negative
  6. Multiple active recovery links -> payment matches only its own
  7. Already-resolved recovery -> duplicate/late webhook is harmless
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.db.session import Base
from app.models.payment import Payment
from app.models.payment_link import PaymentLink
from app.models.recovery_case import RecoveryCase
from app.services import recovery_service
from app.services.payment_gateway import MockPaymentGateway


@pytest.fixture()
def db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session = Session(engine)
    yield session
    session.close()


def _payment(db, *, razorpay_payment_id, razorpay_order_id, status, amount=10000):
    p = Payment(
        razorpay_payment_id=razorpay_payment_id,
        razorpay_order_id=razorpay_order_id,
        amount=amount,
        currency="INR",
        status=status,
        razorpay_created_at=datetime.now(timezone.utc),
    )
    db.add(p)
    db.flush()
    return p


def _awaiting_customer_case_with_link(db, *, failed_payment, plink_id, amount=10000):
    case = RecoveryCase(
        payment_id=failed_payment.id,
        failure_category="BANK_DECLINED",
        amount=amount,
        status="AWAITING_CUSTOMER",
        current_strategy="RETRY_PAYMENT",
        attempt_count=1,
    )
    db.add(case)
    db.flush()
    link = PaymentLink(
        recovery_case_id=case.id,
        razorpay_payment_link_id=plink_id,
        razorpay_short_url=f"https://rzp.io/i/{plink_id}",
        amount=amount,
        currency="INR",
        status="CREATED",
    )
    db.add(link)
    db.flush()
    return case, link


# --- 1. Existing same-order retry still works (regression only) ---

def test_same_order_match_unaffected_by_new_fallback(db):
    """
    Sanity check that adding resolve_via_payment_link doesn't change
    behavior for the original same-order path -- that logic lives in
    payment_service and is untouched; this just confirms
    on_payment_captured_via_retry (which both paths funnel into) still
    behaves identically either way.
    """
    failed = _payment(db, razorpay_payment_id="pay_fail1", razorpay_order_id="order_A", status="FAILED")
    case = RecoveryCase(
        payment_id=failed.id, failure_category="BANK_DECLINED", amount=10000,
        status="IN_PROGRESS", current_strategy="RETRY_PAYMENT", attempt_count=1,
    )
    db.add(case)
    db.flush()

    resolved_case = recovery_service.on_payment_captured_via_retry(db, failed)

    assert resolved_case.status == "RECOVERED"


# --- 2. Payment Link retry (different order) now resolves ---

def test_payment_link_correlation_resolves_different_order(db):
    failed = _payment(db, razorpay_payment_id="pay_fail2", razorpay_order_id="order_original", status="RETRYING")
    case, link = _awaiting_customer_case_with_link(db, failed_payment=failed, plink_id="plink_ABC")

    captured = _payment(
        db, razorpay_payment_id="pay_captured2", razorpay_order_id="order_brand_new_from_link", status="SUCCESS"
    )
    gateway = MockPaymentGateway(paid_links={"plink_ABC": "pay_captured2"})

    result = recovery_service.resolve_via_payment_link(db, captured, gateway)
    assert result.status == "matched"
    assert result.resolved_payment.id == failed.id

    resolved_case = recovery_service.on_payment_captured_via_retry(db, result.resolved_payment)
    assert resolved_case.id == case.id
    assert resolved_case.status == "RECOVERED"
    db.flush()
    db.refresh(link)
    assert link.status == "PAID"
    assert captured.retried_from_payment_id == failed.id


# --- 3. Duplicate captured webhook stays idempotent ---

def test_duplicate_capture_after_resolution_is_idempotent(db):
    """
    Mirrors resolve_unmatched_capture's own guard: once a captured
    payment's retried_from_payment_id is set, a second attempt (e.g. a
    retried Celery task) must not re-resolve or duplicate side effects.
    This tests the service-level idempotency the task guard relies on --
    calling on_payment_captured_via_retry twice for the same case.
    """
    failed = _payment(db, razorpay_payment_id="pay_fail3", razorpay_order_id="order_x", status="RETRYING")
    case, link = _awaiting_customer_case_with_link(db, failed_payment=failed, plink_id="plink_DUP")

    recovery_service.on_payment_captured_via_retry(db, failed)
    assert case.status == "RECOVERED"
    first_resolved_at = case.resolved_at

    # Second call for the same already-resolved payment: on_payment_captured_via_retry
    # looks up a NON-terminal case for payment_id -- none exists anymore -- so it's a no-op.
    second_result = recovery_service.on_payment_captured_via_retry(db, failed)
    assert second_result is None
    assert case.status == "RECOVERED"
    assert case.resolved_at == first_resolved_at


# --- 4. Captured payment with no matching recovery ---

def test_unrelated_payment_leaves_no_active_case_untouched(db):
    captured = _payment(db, razorpay_payment_id="pay_unrelated", razorpay_order_id="order_unrelated", status="SUCCESS")
    gateway = MockPaymentGateway()  # no paid_links configured -- nothing matches

    result = recovery_service.resolve_via_payment_link(db, captured, gateway)

    assert result.status == "not_matched"
    assert captured.retried_from_payment_id is None


# --- 5. Razorpay API failure during fallback ---

def test_gateway_error_yields_retry_not_false_negative(db):
    failed = _payment(db, razorpay_payment_id="pay_fail5", razorpay_order_id="order_e", status="RETRYING")
    _awaiting_customer_case_with_link(db, failed_payment=failed, plink_id="plink_ERR")

    captured = _payment(db, razorpay_payment_id="pay_captured5", razorpay_order_id="order_new5", status="SUCCESS")
    gateway = MockPaymentGateway(force_error={"plink_ERR"})

    result = recovery_service.resolve_via_payment_link(db, captured, gateway)

    assert result.status == "retry"
    assert captured.retried_from_payment_id is None  # nothing mutated on an error path


# --- 6. Multiple active recovery links -> correct one only ---

def test_multiple_active_links_match_only_the_correct_one(db):
    failed_a = _payment(db, razorpay_payment_id="pay_failA", razorpay_order_id="order_A", status="RETRYING")
    case_a, link_a = _awaiting_customer_case_with_link(db, failed_payment=failed_a, plink_id="plink_A")

    failed_b = _payment(db, razorpay_payment_id="pay_failB", razorpay_order_id="order_B", status="RETRYING")
    case_b, link_b = _awaiting_customer_case_with_link(db, failed_payment=failed_b, plink_id="plink_B")

    captured = _payment(db, razorpay_payment_id="pay_captured6", razorpay_order_id="order_new6", status="SUCCESS")
    # Only plink_B is actually paid by this payment.
    gateway = MockPaymentGateway(paid_links={"plink_B": "pay_captured6"})

    result = recovery_service.resolve_via_payment_link(db, captured, gateway)

    assert result.status == "matched"
    assert result.resolved_payment.id == failed_b.id  # NOT failed_a

    recovery_service.on_payment_captured_via_retry(db, result.resolved_payment)
    assert case_b.status == "RECOVERED"
    assert case_a.status == "AWAITING_CUSTOMER"  # untouched


# --- 7. Already-resolved recovery: late/duplicate webhook is harmless ---

def test_late_webhook_after_case_already_recovered_is_harmless(db):
    failed = _payment(db, razorpay_payment_id="pay_fail7", razorpay_order_id="order_g", status="RETRYING")
    case, link = _awaiting_customer_case_with_link(db, failed_payment=failed, plink_id="plink_LATE")

    recovery_service.on_payment_captured_via_retry(db, failed)
    assert case.status == "RECOVERED"

    # A second, unrelated captured payment arrives late and happens to
    # scan the same (now no-longer-active) link -- but the link is PAID,
    # not CREATED, so it's excluded from the candidate scan entirely.
    late_captured = _payment(db, razorpay_payment_id="pay_late7", razorpay_order_id="order_late7", status="SUCCESS")
    gateway = MockPaymentGateway(paid_links={"plink_LATE": "pay_late7"})  # would match IF still a candidate

    result = recovery_service.resolve_via_payment_link(db, late_captured, gateway)

    assert result.status == "not_matched"  # link no longer ACTIVE -> not scanned
    assert case.status == "RECOVERED"  # unchanged