"""
PaymentService: turns a parsed, already-persisted Razorpay webhook event
into Payment state.

Called from webhook_service.py, AFTER the WebhookEvent row is safely
committed -- Phase 1's event storage remains the single source of raw
truth; this module only derives business state from it.

Retry-chain detection (payment.captured after a prior payment.failed on
the same order): when a payment.captured event arrives, we look for the
most recent Payment on the same razorpay_order_id that is in FAILED or
RETRYING status. If found, we link the new captured Payment's
`retried_from_payment_id` to it and transition that prior payment... but
note the prior payment's status is NOT force-transitioned here if it's
already tracked by an open RecoveryCase -- that transition (FAILED/
RETRYING -> handled by RecoveryCase resolution) is recovery_service's
responsibility, since it also needs to resolve the RecoveryCase itself.
payment_service only establishes the link; recovery_service (called
right after, from webhook_service) uses that link to resolve any open
case.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.payment import Payment
from app.schemas.webhook import RazorpayPaymentEntity
from app.services.failure_classifier import classify

logger = get_logger(__name__)


@dataclass(frozen=True)
class PaymentUpdateResult:
    payment: Payment
    is_new: bool
    newly_failed: bool  # True if this update just moved the payment into FAILED
    linked_retry_of: Payment | None  # set if this captured payment resolves a prior failure


def upsert_payment_from_event(
    db: Session,
    event_type: str,
    entity: RazorpayPaymentEntity,
) -> PaymentUpdateResult:
    """
    Create or update the Payment row for a single Razorpay payment entity.

    Idempotent by razorpay_payment_id: if a Payment row for this
    payment_id already exists (e.g. this event type was somehow
    reprocessed -- shouldn't happen given Phase 1's event_id idempotency,
    but we don't want a second layer of bugs to corrupt state if it
    ever did), we update it in place rather than inserting a duplicate.
    """
    existing = db.scalars(
        select(Payment).where(Payment.razorpay_payment_id == entity.id)
    ).first()

    # Standard Checkout creates a server-side PENDING row before Razorpay
    # has minted a pay_* id. Match that placeholder by order so the webhook
    # updates the same Payment row rather than creating a parallel state path.
    if existing is None and entity.order_id:
        existing = db.scalars(
            select(Payment).where(
                Payment.razorpay_order_id == entity.order_id,
                Payment.status == "PENDING",
                Payment.razorpay_payment_id.startswith("checkout_"),
            )
        ).first()
        if existing is not None:
            existing.razorpay_payment_id = entity.id

    is_new = existing is None
    payment = existing or Payment(
        razorpay_payment_id=entity.id,
        razorpay_order_id=entity.order_id,
        customer_email=entity.email,
        customer_contact=entity.contact,
        amount=entity.amount,
        currency=entity.currency,
        razorpay_created_at=datetime.fromtimestamp(entity.created_at, tz=timezone.utc),
        status="PENDING",
    )
    if is_new:
        db.add(payment)
        db.flush()  # assign payment.id before we might reference it below

    newly_failed = False
    linked_retry_of: Payment | None = None

    if event_type == "payment.failed":
        if payment.status == "PENDING":
            payment.transition_to("FAILED")
            newly_failed = True
        payment.failure_code = entity.error_code
        payment.failure_description = entity.error_description
        payment.failure_reason = entity.error_reason
        payment.failure_category = classify(
            entity.error_code, entity.error_description, entity.error_reason
        )

    elif event_type == "payment.captured":
        if payment.status in ("PENDING", "RETRYING"):
            payment.transition_to("SUCCESS")
        elif payment.status == "FAILED":
            # A capture for a payment.status=FAILED row directly (rare --
            # would mean payment.captured arrived after payment.failed
            # for the SAME payment_id, which Razorpay's model doesn't
            # produce; a retry is always a NEW payment_id). Guard it
            # rather than crash on an invalid transition.
            logger.warning(
                "payment.captured received for payment_id=%s which was already "
                "FAILED -- leaving status as-is, this is an unexpected event order",
                entity.id,
            )

        if payment.razorpay_order_id:
            linked_retry_of = _find_prior_failed_payment_on_order(
                db, order_id=payment.razorpay_order_id, exclude_payment_id=payment.id
            )
            if linked_retry_of is not None:
                payment.retried_from_payment_id = linked_retry_of.id
                logger.info(
                    "Linked retry: payment_id=%s (captured) resolves prior "
                    "failure on payment_id=%s (order_id=%s)",
                    entity.id,
                    linked_retry_of.razorpay_payment_id,
                    payment.razorpay_order_id,
                )

    return PaymentUpdateResult(
        payment=payment,
        is_new=is_new,
        newly_failed=newly_failed,
        linked_retry_of=linked_retry_of,
    )


def _find_prior_failed_payment_on_order(
    db: Session, order_id: str, exclude_payment_id: int | None
) -> Payment | None:
    """
    Most recent Payment on the same order_id that is currently FAILED or
    RETRYING -- i.e. a failure this new capture likely resolves.
    """
    stmt = (
        select(Payment)
        .where(
            Payment.razorpay_order_id == order_id,
            Payment.status.in_(("FAILED", "RETRYING")),
        )
        .order_by(Payment.razorpay_created_at.desc())
    )
    if exclude_payment_id is not None:
        stmt = stmt.where(Payment.id != exclude_payment_id)
    return db.scalars(stmt).first()
