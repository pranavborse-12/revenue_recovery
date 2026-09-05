"""
Idempotent seed script for the deterministic demo account.

    python -m scripts.seed_demo_account

Creates (or reuses, if already present):
  - Organization "AcmeCloud Technologies" (is_demo=True)
  - User demo@revflow.ai (role=admin) under that organization
  - A small set of synthetic Payments / RecoveryCases / RecoveryActions /
    PaymentLinks / RecoveryCommunications / AIRecoveryDecisions, all
    organization_id=<AcmeCloud Technologies>.id and Payment.is_synthetic=True.

Safe to run repeatedly: every lookup is by a natural/unique key
(organization name, user email, payment razorpay_payment_id) before any
insert, so re-running does not duplicate rows.

Uses only synthetic customer data (test emails/contacts) and Razorpay
Test-Mode-style ids (never real Razorpay ids) and small INR test amounts.
"""

from datetime import datetime, timedelta, timezone

from app.db.session import SessionLocal
from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.organization import Organization
from app.models.payment import Payment
from app.models.payment_link import PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.models.recovery_communication import RecoveryCommunication
from app.models.user import User

DEMO_ORG_NAME = "AcmeCloud Technologies"
DEMO_USER_EMAIL = "demo@revflow.ai"


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _get_or_create_organization(db) -> Organization:
    org = db.query(Organization).filter(Organization.name == DEMO_ORG_NAME).first()
    if org is not None:
        return org
    org = Organization(name=DEMO_ORG_NAME, industry="SaaS", is_demo=True)
    db.add(org)
    db.flush()
    return org


def _get_or_create_user(db, org: Organization) -> User:
    user = db.query(User).filter(User.email == DEMO_USER_EMAIL).first()
    if user is not None:
        return user
    user = User(email=DEMO_USER_EMAIL, organization_id=org.id, role="admin")
    db.add(user)
    db.flush()
    return user


def _get_or_create_payment(db, org: Organization, *, razorpay_payment_id: str, **kwargs) -> tuple[Payment, bool]:
    existing = db.query(Payment).filter(Payment.razorpay_payment_id == razorpay_payment_id).first()
    if existing is not None:
        return existing, False
    payment = Payment(
        organization_id=org.id,
        razorpay_payment_id=razorpay_payment_id,
        is_synthetic=True,
        **kwargs,
    )
    db.add(payment)
    db.flush()
    return payment, True


def _seed_recovered_case(db, org: Organization) -> None:
    payment, created = _get_or_create_payment(
        db, org,
        razorpay_payment_id="pay_demo_synthetic_0001",
        razorpay_order_id="order_demo_synthetic_0001",
        customer_email="synthetic.customer1@example-test.com",
        customer_contact="+911234500001",
        amount=49900,
        currency="INR",
        status="SUCCESS",
        failure_code="BAD0001",
        failure_description="Insufficient funds in the account",
        failure_reason="insufficient_funds",
        failure_category="INSUFFICIENT_FUNDS",
        razorpay_created_at=_utcnow() - timedelta(days=5),
    )
    if not created:
        return

    case = RecoveryCase(
        payment_id=payment.id,
        organization_id=org.id,
        failure_category="INSUFFICIENT_FUNDS",
        amount=payment.amount,
        status="RECOVERED",
        current_strategy="RETRY_PAYMENT",
        attempt_count=1,
        resolved_at=_utcnow() - timedelta(days=4),
    )
    db.add(case)
    db.flush()

    db.add(RecoveryAction(
        recovery_case_id=case.id,
        organization_id=org.id,
        action_type="RETRY_PAYMENT",
        status="SUCCESS",
        attempt_number=1,
        scheduled_at=_utcnow() - timedelta(days=4, hours=1),
        executed_at=_utcnow() - timedelta(days=4),
        result="retry payment captured",
    ))

    db.add(AIRecoveryDecision(
        recovery_case_id=case.id,
        organization_id=org.id,
        recommended_action="RETRY_PAYMENT",
        recommended_delay_minutes=30,
        confidence=0.82,
        reason="Synthetic demo decision: insufficient-funds retries recover often within 30 minutes.",
        model="synthetic-seed",
        agent_role="final",
        provider=None,
        accepted=True,
        executed=True,
        outcome="retry payment captured",
    ))


def _seed_awaiting_customer_case(db, org: Organization) -> None:
    payment, created = _get_or_create_payment(
        db, org,
        razorpay_payment_id="pay_demo_synthetic_0002",
        razorpay_order_id="order_demo_synthetic_0002",
        customer_email="synthetic.customer2@example-test.com",
        customer_contact="+911234500002",
        amount=129900,
        currency="INR",
        status="FAILED",
        failure_code="BAD0002",
        failure_description="Card declined by issuing bank",
        failure_reason="bank_declined",
        failure_category="BANK_DECLINED",
        razorpay_created_at=_utcnow() - timedelta(days=2),
    )
    if not created:
        return

    case = RecoveryCase(
        payment_id=payment.id,
        organization_id=org.id,
        failure_category="BANK_DECLINED",
        amount=payment.amount,
        status="AWAITING_CUSTOMER",
        current_strategy="RETRY_PAYMENT",
        attempt_count=3,
    )
    db.add(case)
    db.flush()

    for attempt in range(1, 4):
        db.add(RecoveryAction(
            recovery_case_id=case.id,
            organization_id=org.id,
            action_type="RETRY_PAYMENT",
            status="FAILED",
            attempt_number=attempt,
            scheduled_at=_utcnow() - timedelta(days=2 - attempt * 0.2),
            executed_at=_utcnow() - timedelta(days=2 - attempt * 0.2),
            result="gateway declined: insufficient funds",
        ))

    link = PaymentLink(
        recovery_case_id=case.id,
        organization_id=org.id,
        razorpay_payment_link_id="plink_demo_synthetic_0002",
        razorpay_short_url="https://rzp.io/i/demo-synthetic-0002",
        amount=payment.amount,
        currency=payment.currency,
        status="CREATED",
        expires_at=_utcnow() + timedelta(days=2),
    )
    db.add(link)

    db.add(RecoveryCommunication(
        recovery_case_id=case.id,
        organization_id=org.id,
        channel="EMAIL",
        type="PAYMENT_LINK",
        status="SENT",
        provider_message_id="synthetic-msg-0002",
        sent_at=_utcnow() - timedelta(hours=6),
    ))


def _seed_open_case(db, org: Organization) -> None:
    payment, created = _get_or_create_payment(
        db, org,
        razorpay_payment_id="pay_demo_synthetic_0003",
        razorpay_order_id="order_demo_synthetic_0003",
        customer_email="synthetic.customer3@example-test.com",
        customer_contact="+911234500003",
        amount=19900,
        currency="INR",
        status="FAILED",
        failure_code="BAD0003",
        failure_description="Network timeout while contacting issuer",
        failure_reason="temporary_network_error",
        failure_category="TEMPORARY_NETWORK_ERROR",
        razorpay_created_at=_utcnow() - timedelta(hours=3),
    )
    if not created:
        return

    case = RecoveryCase(
        payment_id=payment.id,
        organization_id=org.id,
        failure_category="TEMPORARY_NETWORK_ERROR",
        amount=payment.amount,
        status="OPEN",
        current_strategy="RETRY_PAYMENT",
        attempt_count=0,
    )
    db.add(case)


def run_seed() -> dict:
    db = SessionLocal()
    try:
        org = _get_or_create_organization(db)
        user = _get_or_create_user(db, org)
        _seed_recovered_case(db, org)
        _seed_awaiting_customer_case(db, org)
        _seed_open_case(db, org)
        db.commit()
        return {"organization_id": org.id, "organization_name": org.name, "user_id": user.id, "user_email": user.email}
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    result = run_seed()
    print(f"Seeded demo organization_id={result['organization_id']} "
          f"({result['organization_name']}), user_id={result['user_id']} ({result['user_email']})")