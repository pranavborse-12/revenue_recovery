"""
historical_intelligence: recovery-rate evidence, computed by SQL
aggregation over real, already-persisted rows -- RecoveryAction (every
retry actually attempted) and PaymentLink (every customer-recovery link
actually created), joined to their RecoveryCase's final outcome. No ML,
no training, no separate stats table -- these are live queries.

One tier only, deliberately: the project spec's "merchant + failure +
action -> merchant + failure -> global failure + action" hierarchy
assumes a Merchant dimension this single-tenant schema doesn't have (one
Razorpay account = the only "merchant" there is). Per project decision,
this is NOT faked -- there is exactly one tier here: failure_category +
action, across all data (synthetic seed history combined with real
outcomes, intentionally -- see scripts/seed_synthetic_history.py).

Includes synthetic AND real rows together by design (the project's
"bootstrap history + real outcomes -> better evidence over time" model)
-- Payment.is_synthetic is available for anyone who wants to filter it
out, but this function deliberately does not, since a seeded and a real
case both represent one real question: "did this action recover this
kind of failure?"
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.payment_link import PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase


@dataclass(frozen=True)
class ActionEvidence:
    attempts: int
    recovered: int
    recovery_rate: float
    sample_size: int  # same as attempts -- named separately per the project's evidence schema


def get_recovery_evidence(db: Session, failure_category: str) -> dict[str, ActionEvidence]:
    """
    {action_name: ActionEvidence} for whichever actions have at least one
    real data point for this failure_category. An action absent from the
    result means "no evidence available" -- callers (and the prompts
    that pass this along) must not treat a missing action as a 0% rate;
    it means untested, not tried-and-failed.
    """
    evidence: dict[str, ActionEvidence] = {}

    retry_evidence = _retry_payment_evidence(db, failure_category)
    if retry_evidence is not None:
        evidence["RETRY_PAYMENT"] = retry_evidence

    link_evidence = _send_payment_link_evidence(db, failure_category)
    if link_evidence is not None:
        evidence["SEND_PAYMENT_LINK"] = link_evidence

    return evidence


def _retry_payment_evidence(db: Session, failure_category: str) -> ActionEvidence | None:
    """One row per actual retry attempt (RecoveryAction), not per case."""
    rows = db.execute(
        select(RecoveryAction.status, func.count())
        .join(RecoveryCase, RecoveryAction.recovery_case_id == RecoveryCase.id)
        .where(
            RecoveryCase.failure_category == failure_category,
            RecoveryAction.action_type == "RETRY_PAYMENT",
            RecoveryAction.executed_at.is_not(None),
        )
        .group_by(RecoveryAction.status)
    ).all()

    attempts = sum(count for _, count in rows)
    if attempts == 0:
        return None
    recovered = sum(count for status, count in rows if status == "SUCCESS")
    return ActionEvidence(
        attempts=attempts, recovered=recovered, recovery_rate=round(recovered / attempts, 4), sample_size=attempts
    )


def _send_payment_link_evidence(db: Session, failure_category: str) -> ActionEvidence | None:
    """
    One "attempt" per case that received a payment link for this
    category (a case that got one link and then another after ignoring
    the first still only tried the intervention once, in the sense that
    matters for this statistic: did customer-assisted recovery work for
    this case).
    """
    case_ids_with_link = (
        select(PaymentLink.recovery_case_id)
        .join(RecoveryCase, PaymentLink.recovery_case_id == RecoveryCase.id)
        .where(RecoveryCase.failure_category == failure_category)
        .distinct()
        .subquery()
    )

    attempts = db.scalar(select(func.count()).select_from(case_ids_with_link)) or 0
    if attempts == 0:
        return None

    recovered = (
        db.scalar(
            select(func.count(RecoveryCase.id)).where(
                RecoveryCase.id.in_(select(case_ids_with_link.c.recovery_case_id)),
                RecoveryCase.status == "RECOVERED",
            )
        )
        or 0
    )
    return ActionEvidence(
        attempts=attempts, recovered=recovered, recovery_rate=round(recovered / attempts, 4), sample_size=attempts
    )


def evidence_to_prompt_dict(evidence: dict[str, ActionEvidence]) -> dict:
    """Plain-dict form for JSON serialization into an LLM prompt."""
    return {
        action: {"attempts": e.attempts, "recovered": e.recovered, "recovery_rate": e.recovery_rate, "sample_size": e.sample_size}
        for action, e in evidence.items()
    }