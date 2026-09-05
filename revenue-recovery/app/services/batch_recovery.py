"""
batch_recovery: measures actual outcomes across every RecoveryCase, not
a simulator. Revenue is attributed once per RecoveryCase (RecoveryCase.
amount already represents the underlying order's amount, set once at
case creation from Payment.amount -- it is never re-summed per
RecoveryAction, so a case retried 3 times before recovering still
contributes exactly one case's worth of revenue, never three).
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.payment_link import PaymentLink
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.models.recovery_communication import RecoveryCommunication


@dataclass(frozen=True)
class BatchResult:
    cases_processed: int
    revenue_at_risk: int  # sum of amount for cases still unresolved (OPEN/IN_PROGRESS/AWAITING_CUSTOMER)
    recovered_revenue: int  # sum of amount for RECOVERED cases only
    revenue_recovery_rate: float  # recovered_revenue / (recovered_revenue + amount of EXHAUSTED/CANCELLED)
    recovered_cases: int
    escalated_cases: int  # EXHAUSTED cases that had at least one executed MANUAL_REVIEW agent decision
    stopped_cases: int  # EXHAUSTED cases with no agent involvement (deterministic exhaustion)
    retries_executed: int
    payment_links_created: int
    emails_sent: int
    ai_decisions: int
    ai_decisions_executed: int
    ai_policy_rejections: int


def run_batch(db: Session, organization_id: int) -> BatchResult:
    """
    Same measurement as before, scoped to a single organization.
    `organization_id` is required (not optional) so a caller can never
    forget to scope it and get a cross-tenant report by accident -- the
    one deployment-wide report this used to produce is no longer a
    supported mode now that RecoveryCase etc. are tenant-owned.
    """
    cases_processed = (
        db.scalar(select(func.count(RecoveryCase.id)).where(RecoveryCase.organization_id == organization_id))
        or 0
    )

    revenue_at_risk = (
        db.scalar(
            select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
                RecoveryCase.status.in_(("OPEN", "IN_PROGRESS", "AWAITING_CUSTOMER")),
                RecoveryCase.organization_id == organization_id,
            )
        )
        or 0
    )
    recovered_revenue = (
        db.scalar(
            select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
                RecoveryCase.status == "RECOVERED", RecoveryCase.organization_id == organization_id
            )
        )
        or 0
    )
    unrecovered_terminal_revenue = (
        db.scalar(
            select(func.coalesce(func.sum(RecoveryCase.amount), 0)).where(
                RecoveryCase.status.in_(("EXHAUSTED", "CANCELLED")),
                RecoveryCase.organization_id == organization_id,
            )
        )
        or 0
    )
    resolved_revenue = recovered_revenue + unrecovered_terminal_revenue
    revenue_recovery_rate = (recovered_revenue / resolved_revenue) if resolved_revenue > 0 else 0.0

    recovered_cases = (
        db.scalar(
            select(func.count(RecoveryCase.id)).where(
                RecoveryCase.status == "RECOVERED", RecoveryCase.organization_id == organization_id
            )
        )
        or 0
    )

    escalated_case_ids = set(
        db.scalars(
            select(AIRecoveryDecision.recovery_case_id).where(
                AIRecoveryDecision.recommended_action == "MANUAL_REVIEW",
                AIRecoveryDecision.executed.is_(True),
                AIRecoveryDecision.organization_id == organization_id,
            )
        )
    )
    exhausted_case_ids = set(
        db.scalars(
            select(RecoveryCase.id).where(
                RecoveryCase.status == "EXHAUSTED", RecoveryCase.organization_id == organization_id
            )
        )
    )
    escalated_cases = len(exhausted_case_ids & escalated_case_ids)
    stopped_cases = len(exhausted_case_ids - escalated_case_ids)

    retries_executed = (
        db.scalar(
            select(func.count(RecoveryAction.id)).where(
                RecoveryAction.executed_at.is_not(None), RecoveryAction.organization_id == organization_id
            )
        )
        or 0
    )
    payment_links_created = (
        db.scalar(select(func.count(PaymentLink.id)).where(PaymentLink.organization_id == organization_id)) or 0
    )
    emails_sent = (
        db.scalar(
            select(func.count(RecoveryCommunication.id)).where(
                RecoveryCommunication.status == "SENT",
                RecoveryCommunication.organization_id == organization_id,
            )
        )
        or 0
    )

    ai_decisions = (
        db.scalar(select(func.count(AIRecoveryDecision.id)).where(AIRecoveryDecision.organization_id == organization_id))
        or 0
    )
    ai_decisions_executed = (
        db.scalar(
            select(func.count(AIRecoveryDecision.id)).where(
                AIRecoveryDecision.executed.is_(True), AIRecoveryDecision.organization_id == organization_id
            )
        )
        or 0
    )
    ai_policy_rejections = (
        db.scalar(
            select(func.count(AIRecoveryDecision.id)).where(
                AIRecoveryDecision.accepted.is_(False), AIRecoveryDecision.organization_id == organization_id
            )
        )
        or 0
    )

    return BatchResult(
        cases_processed=cases_processed,
        revenue_at_risk=revenue_at_risk,
        recovered_revenue=recovered_revenue,
        revenue_recovery_rate=round(revenue_recovery_rate, 4),
        recovered_cases=recovered_cases,
        escalated_cases=escalated_cases,
        stopped_cases=stopped_cases,
        retries_executed=retries_executed,
        payment_links_created=payment_links_created,
        emails_sent=emails_sent,
        ai_decisions=ai_decisions,
        ai_decisions_executed=ai_decisions_executed,
        ai_policy_rejections=ai_policy_rejections,
    )