"""
RecoveryContextBuilder: RecoveryCase -> small structured dict for the AI
decision service.

Deliberately excludes:
  - PII (customer email/contact) -- the AI doesn't need identity to
    recommend an action/delay.
  - Free-text fields (failure_description, error_description) -- keeps
    the AI's input entirely our own structured/categorical data
  - Cross-case "customer behavior" signals (e.g. success-rate-by-hour)
    -- this project's schema has no reliable per-customer identity join
    across cases, and current data volume is far too small to support
    that kind of claim without fabricating a pattern. Only this case's
    own recorded attempt history is used.
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.retry_policy import get_retry_policy
from app.models.payment_link import PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase


def build_recovery_context(db: Session, case: RecoveryCase) -> dict:
    actions = list(
        db.scalars(
            select(RecoveryAction)
            .where(RecoveryAction.recovery_case_id == case.id)
            .order_by(RecoveryAction.attempt_number)
        )
    )

    # Only attempts that actually ran (have executed_at) contribute a
    # data point -- a still-PENDING action isn't a signal yet.
    prior_attempts = [
        {"attempt_number": a.attempt_number, "status": a.status, "hour_of_day": a.executed_at.hour}
        for a in actions
        if a.executed_at is not None
    ]

    payment_link_used_before = (
        db.scalar(
            select(func.count(PaymentLink.id)).where(PaymentLink.recovery_case_id == case.id)
        )
        or 0
    ) > 0

    return {
        "amount": case.amount,
        "failure_category": case.failure_category,
        "attempt_count": case.attempt_count,
        "max_automatic_attempts": get_retry_policy().max_attempts,
        "prior_attempts": prior_attempts,
        "payment_link_used_before": payment_link_used_before,
        "case_status": case.status,
    }