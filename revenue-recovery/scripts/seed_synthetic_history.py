"""
Seed synthetic historical recovery trajectories for demonstrating
historical_intelligence.py without hundreds of manual Razorpay Test
Mode transactions.

SAFETY (not a policy promise -- structural): every row this script
inserts is created ALREADY in a terminal state -- Payment.status in
(SUCCESS, FAILED); RecoveryCase.status in (RECOVERED, EXHAUSTED);
RecoveryAction.status in (SUCCESS, FAILED). No PENDING RecoveryAction is
ever created, and no live webhook event is ever generated. Every entry
point that could act on a row (execute_recovery_action, the webhook
handler, the live agent) requires either a PENDING action or an
incoming webhook -- neither exists for anything this script writes, so
nothing live can ever pick these rows up, touch a real Razorpay API on
their behalf, or send a real customer communication for them.

Payment.is_synthetic=True marks every row for humans/queries. It is a
label, not the safety mechanism above.

Scenario catalogue: 16 (error_code, error_description, error_reason,
method) tuples, all using error_reason values already present in
failure_classifier.py's real _ERROR_REASON_MAP -- run through the SAME
classify() function real webhooks use, not a separate/invented mapping.

CATEGORY_DYNAMICS below are SIMULATION PARAMETERS ONLY -- they decide
how many generated cases land RECOVERED vs EXHAUSTED, and via which
action. They are NEVER read by the AI; the AI only ever sees the
resulting AGGREGATE COUNTS, computed the same way from this synthetic
data as from real data (historical_intelligence.py).

Run from your project root:
    uv run python scripts/seed_synthetic_history.py [--per-scenario N]
"""
import argparse
import random
import sys
from datetime import datetime, timedelta, timezone

sys.path.insert(0, ".")

from app.db.session import SessionLocal  # noqa: E402
from app.models.payment import Payment  # noqa: E402
from app.models.payment_link import PaymentLink  # noqa: E402
from app.models.recovery_action import RecoveryAction  # noqa: E402
from app.models.recovery_case import RecoveryCase  # noqa: E402
from app.models.organization import Organization  # noqa: E402
from app.models.user import User  # noqa: E402
from app.services.failure_classifier import classify  # noqa: E402
from sqlalchemy import select  # noqa: E402

SCENARIOS = [
    ("BAD_REQUEST_ERROR", "Insufficient balance in the customer's account", "insufficient_funds", "card"),
    ("BAD_REQUEST_ERROR", "Card has expired", "card_expired", "card"),
    ("BAD_REQUEST_ERROR", "Card is disabled for online payments", "card_disabled_for_online_payments", "card"),
    ("BAD_REQUEST_ERROR", "Card not enrolled for authentication", "card_not_enrolled", "card"),
    ("BAD_REQUEST_ERROR", "Debit instrument is inactive", "debit_instrument_inactive", "card"),
    ("BAD_REQUEST_ERROR", "Debit instrument is blocked", "debit_instrument_blocked", "card"),
    ("BAD_REQUEST_ERROR", "Incorrect CVV entered", "incorrect_cvv", "card"),
    ("BAD_REQUEST_ERROR", "Card was declined by the issuing bank", "card_declined", "card"),
    ("BAD_REQUEST_ERROR", "Payment failed", "payment_failed", "upi"),
    ("BAD_REQUEST_ERROR", "Authentication failed", "authentication_failed", "card"),
    ("BAD_REQUEST_ERROR", "Payment risk check failed", "payment_risk_check_failed", "card"),
    ("BAD_REQUEST_ERROR", "Transaction limit exceeded", "transaction_limit_exceeded", "upi"),
    ("GATEWAY_ERROR", "Bank's servers are experiencing issues", "bank_technical_error", "netbanking"),
    ("GATEWAY_ERROR", "Gateway is currently unavailable", "gateway_technical_error", "card"),
    ("GATEWAY_ERROR", "Payment request timed out", "payment_timed_out", "upi"),
    ("BAD_REQUEST_ERROR", "Payment was cancelled", "payment_cancelled", "upi"),
]

# Simulation parameters only -- see module docstring. Loosely modelled
# on the pattern the project brief described (retry works better for
# transient issues, payment link works better when the payment method
# itself was the problem).
CATEGORY_DYNAMICS = {
    "TEMPORARY_NETWORK_ERROR": {"retry_recovery_rate": 0.65, "link_recovery_rate": 0.55},
    "INSUFFICIENT_FUNDS": {"retry_recovery_rate": 0.18, "link_recovery_rate": 0.64},
    "BANK_DECLINED": {"retry_recovery_rate": 0.28, "link_recovery_rate": 0.58},
    "PAYMENT_METHOD_EXPIRED": {"retry_recovery_rate": 0.05, "link_recovery_rate": 0.71},
    "PAYMENT_METHOD_INVALID": {"retry_recovery_rate": 0.08, "link_recovery_rate": 0.66},
    "UNKNOWN": {"retry_recovery_rate": 0.15, "link_recovery_rate": 0.30},
}
LINK_ATTEMPT_PROBABILITY_AFTER_RETRY_FAILS = 0.70


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _seed_one_case(db, organization_id: int, rng: random.Random, counter: int, error_code: str, error_description: str, error_reason: str, method: str) -> None:
    category = classify(error_code, error_description, error_reason)
    dynamics = CATEGORY_DYNAMICS[category]
    amount = rng.randint(500, 500_000)  # paise: ~Rs 5 - Rs 5,000
    created_at = _utcnow() - timedelta(days=rng.randint(1, 180))

    payment = Payment(
        razorpay_payment_id=f"pay_SYNTH{counter:08d}",
        razorpay_order_id=f"order_SYNTH{counter:08d}",
        amount=amount, currency="INR", status="FAILED",
        failure_code=error_code, failure_description=error_description,
        failure_reason=error_reason, failure_category=category,
        is_synthetic=True, organization_id=organization_id, razorpay_created_at=created_at,
    )
    db.add(payment)
    db.flush()

    case = RecoveryCase(
        payment_id=payment.id, organization_id=organization_id, failure_category=category, amount=amount,
        status="IN_PROGRESS", current_strategy="RETRY_PAYMENT", attempt_count=1,
        created_at=created_at, updated_at=created_at,
    )
    db.add(case)
    db.flush()

    retry_recovered = rng.random() < dynamics["retry_recovery_rate"]
    db.add(RecoveryAction(
        recovery_case_id=case.id, organization_id=organization_id, action_type="RETRY_PAYMENT",
        status="SUCCESS" if retry_recovered else "FAILED", attempt_number=1,
        scheduled_at=created_at, executed_at=created_at + timedelta(minutes=30),
        result="synthetic: retry recovered" if retry_recovered else "synthetic: retry failed",
    ))

    if retry_recovered:
        payment.status = "SUCCESS"
        case.status = "RECOVERED"
        case.resolved_at = created_at + timedelta(minutes=30)
        db.flush()
        return

    tried_link = rng.random() < LINK_ATTEMPT_PROBABILITY_AFTER_RETRY_FAILS
    if not tried_link:
        case.status = "EXHAUSTED"
        case.resolved_at = created_at + timedelta(hours=1)
        db.flush()
        return

    link_recovered = rng.random() < dynamics["link_recovery_rate"]
    db.add(PaymentLink(
        recovery_case_id=case.id, organization_id=organization_id, razorpay_payment_link_id=f"plink_SYNTH{counter:08d}",
        razorpay_short_url=f"https://rzp.io/i/plink_SYNTH{counter:08d}",
        amount=amount, currency="INR", status="PAID" if link_recovered else "CREATED",
        created_at=created_at + timedelta(hours=1),
    ))
    case.status = "RECOVERED" if link_recovered else "EXHAUSTED"
    case.resolved_at = created_at + timedelta(hours=2) if link_recovered else None
    db.flush()


def main(per_scenario: int) -> None:
    db = SessionLocal()
    counter = 1
    try:
        organization = db.scalar(select(Organization).where(Organization.name == "AcmeCloud Technologies"))
        if organization is None:
            organization = Organization(name="AcmeCloud Technologies", industry="Software", is_demo=True)
            db.add(organization)
            db.flush()
        else:
            organization.is_demo = True
        user = db.scalar(select(User).where(User.email == "demo@revflow.ai"))
        if user is None:
            db.add(User(email="demo@revflow.ai", organization_id=organization.id, role="admin"))
        else:
            user.organization_id, user.role = organization.id, "admin"

        existing_synthetic = list(db.scalars(select(Payment).where(Payment.is_synthetic.is_(True))))
        if existing_synthetic:
            for payment in existing_synthetic:
                payment.organization_id = organization.id
            for model in (RecoveryCase, RecoveryAction, PaymentLink):
                db.query(model).filter(model.organization_id.is_(None)).update({"organization_id": organization.id})
            db.commit()
            print(f"Demo merchant already seeded: {len(existing_synthetic)} synthetic recovery trajectories associated with AcmeCloud Technologies.")
            return

        rng = random.Random(20260905)
        for error_code, error_description, error_reason, method in SCENARIOS:
            for _ in range(per_scenario):
                _seed_one_case(db, organization.id, rng, counter, error_code, error_description, error_reason, method)
                counter += 1
        db.commit()
        print(f"Seeded {counter - 1} synthetic recovery trajectories across {len(SCENARIOS)} scenarios.")
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-scenario", type=int, default=40)
    args = parser.parse_args()
    main(args.per_scenario)
