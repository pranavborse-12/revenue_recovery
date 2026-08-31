"""
recovery_agent: one bounded decision-and-execute step for a recovery
case. Never calls itself, never loops -- it's invoked once per
deterministic decision point (see recovery_service.py's two call sites),
same as the audit-only version was, except now its result can gate what
the caller does next.

    build context -> AI recommendation -> validate_ai_recommendation()
        -> tool call -> record decision

Any failure anywhere in that chain (AI unavailable, invalid output,
policy rejection, tool precondition failure, tool execution error)
results in handled=False -- the caller always has a safe, already-
working deterministic path to fall back to. AI confidence is never
authority; a "handled=True" only ever happens after
validate_ai_recommendation() (the existing, unmodified policy check)
has already said yes.
"""

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.logging import get_logger
from app.core.retry_policy import get_retry_policy
from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.payment import Payment
from app.models.recovery_case import TERMINAL_RECOVERY_CASE_STATUSES, RecoveryCase
from app.services import agent_tools, recovery_context
from app.services.agent_tools import AgentToolError
from app.services.ai_recovery_service import get_ai_recovery_service

logger = get_logger(__name__)


@dataclass(frozen=True)
class AgentStepResult:
    handled: bool  # True only if a tool call was made AND succeeded
    decision_id: int | None = None


def agent_has_budget(db: Session, case: RecoveryCase) -> bool:
    """
    False whenever the agent should not even be asked: disabled, case
    already terminal, or its execution budget (RetryPolicy.max_attempts,
    counted by rows where executed=True -- per project decision, not a
    separate config knob) is spent.
    """
    if not get_settings().AI_AGENT_ENABLED:
        return False
    if case.status in TERMINAL_RECOVERY_CASE_STATUSES:
        return False
    used = (
        db.scalar(
            select(func.count(AIRecoveryDecision.id)).where(
                AIRecoveryDecision.recovery_case_id == case.id,
                AIRecoveryDecision.executed.is_(True),
            )
        )
        or 0
    )
    return used < get_retry_policy().max_attempts


def _get_gateway():
    from app.services.payment_gateway import RazorpayPaymentGateway

    return RazorpayPaymentGateway()


def try_agent_intervention(
    db: Session, case: RecoveryCase, *, recovery_action_id: int | None
) -> AgentStepResult:
    """
    Caller MUST have already confirmed agent_has_budget(db, case) is
    True. Doesn't re-check it here to avoid a second, possibly-stale
    query in the same call -- the caller's check and this call happen in
    the same transaction/moment.
    """
    from app.services.email_provider import get_email_provider
    from app.services.recovery_service import validate_ai_recommendation

    service = get_ai_recovery_service()
    if service is None:
        return AgentStepResult(handled=False)

    context = recovery_context.build_recovery_context(db, case)
    recommendation = service.recommend(context)
    if recommendation is None:
        return AgentStepResult(handled=False)

    accepted, rejection_reason = validate_ai_recommendation(case, recommendation)

    if not accepted or recommendation.action == "WAIT":
        db.add(
            AIRecoveryDecision(
                recovery_case_id=case.id, recovery_action_id=recovery_action_id,
                recommended_action=recommendation.action, recommended_delay_minutes=recommendation.delay_minutes,
                confidence=recommendation.confidence, reason=recommendation.reason, model=service._model,
                accepted=accepted, rejection_reason=rejection_reason if not accepted else "WAIT: deferred",
                executed=False,
            )
        )
        db.flush()
        return AgentStepResult(handled=False)

    payment = db.get(Payment, case.payment_id)
    gateway = _get_gateway()
    email_provider = get_email_provider()

    try:
        if recommendation.action == "RETRY_PAYMENT":
            outcome = agent_tools.retry_payment(db, case)
        elif recommendation.action == "SEND_PAYMENT_LINK":
            outcome = agent_tools.send_recovery_email(db, case, payment, gateway, email_provider)
        elif recommendation.action == "MANUAL_REVIEW":
            if case.status in ("OPEN", "IN_PROGRESS", "AWAITING_CUSTOMER"):
                case.transition_to("EXHAUSTED")
            outcome = "manual review: case marked EXHAUSTED for human follow-up"
        else:  # pragma: no cover -- schema already restricts to known actions
            raise AgentToolError(f"no tool for action {recommendation.action}")
        succeeded = True
    except AgentToolError as exc:
        logger.warning("recovery_case_id=%s agent tool failed: %s", case.id, exc)
        outcome = str(exc)
        succeeded = False

    decision = AIRecoveryDecision(
        recovery_case_id=case.id, recovery_action_id=recovery_action_id,
        recommended_action=recommendation.action, recommended_delay_minutes=recommendation.delay_minutes,
        confidence=recommendation.confidence, reason=recommendation.reason, model=service._model,
        accepted=True, rejection_reason=None, executed=True, outcome=outcome,
    )
    db.add(decision)
    db.flush()

    logger.info(
        "recovery_case_id=%s agent executed action=%s succeeded=%s outcome=%s",
        case.id, recommendation.action, succeeded, outcome,
    )
    return AgentStepResult(handled=succeeded, decision_id=decision.id)