"""
Celery task: request_ai_recommendation.

    RecoveryCase (a decision point was just reached)
          |
    this task
          |
    recovery_agent.get_multi_agent_recommendation()
          |  (3 independent agent opinions, each recorded;
          |   reconciled deterministically)
          |
    recovery_service.validate_ai_recommendation()  -- policy check
          |
    final AIRecoveryDecision row stored (executed=False, always)

Audit-only: this task never writes to RecoveryCase, RecoveryAction, or
PaymentLink -- get_multi_agent_recommendation's per-agent audit writes
and this task's own final-row write are its only side effects. A bug
here cannot corrupt recovery state.

Multi-agent change: was previously a single Mistral call via
ai_recovery_service.get_ai_recovery_service().recommend(); now uses the
same 3-agent orchestrator the live agent path uses (recovery_agent.py),
so audit-only mode shows what the full multi-agent system would have
done, not just the old single-provider baseline.

Celery-level retries are enabled (unlike execute_recovery_action) because
a failure here is purely infrastructural (AI provider hiccup) -- there's
no business-level "policy" governing when to retry an audit computation,
unlike a real payment retry.
"""

from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.recovery_case import RecoveryCase
from app.services import recovery_agent, recovery_service
from app.tasks.celery_app import celery_app

configure_logging()
logger = get_logger(__name__)


@celery_app.task(
    name="app.tasks.ai_recovery_tasks.request_ai_recommendation",
    bind=True,
    max_retries=2,
    default_retry_delay=15,
)
def request_ai_recommendation(self, recovery_case_id: int, recovery_action_id: int | None) -> str:
    db = SessionLocal()
    try:
        case = db.get(RecoveryCase, recovery_case_id)
        if case is None:
            logger.warning("request_ai_recommendation: recovery_case_id=%s not found", recovery_case_id)
            return "skipped: not found"

        recommendation = recovery_agent.get_multi_agent_recommendation(
            db, case, recovery_action_id=recovery_action_id
        )
        if recommendation is None:
            db.commit()  # persist the per-agent opinion rows even when reconciliation found nothing confident
            logger.info("recovery_case_id=%s: no usable multi-agent recommendation", case.id)
            return "skipped: no valid recommendation"

        accepted, rejection_reason = recovery_service.validate_ai_recommendation(case, recommendation)

        db.add(
            AIRecoveryDecision(
                recovery_case_id=case.id,
                recovery_action_id=recovery_action_id,
                recommended_action=recommendation.action,
                recommended_delay_minutes=recommendation.delay_minutes,
                confidence=recommendation.confidence,
                reason=recommendation.reason,
                model="multi-agent",
                agent_role="final",
                provider=None,
                accepted=accepted,
                rejection_reason=rejection_reason,
                executed=False,  # audit-only task: NEVER executes, regardless of accepted
            )
        )
        db.commit()

        logger.info(
            "recovery_case_id=%s AI recommended action=%s delay=%s confidence=%.2f accepted=%s (%s)",
            case.id, recommendation.action, recommendation.delay_minutes,
            recommendation.confidence, accepted, rejection_reason or "n/a",
        )
        return f"stored: accepted={accepted}"

    except Exception:
        db.rollback()
        logger.exception("request_ai_recommendation: unexpected error for recovery_case_id=%s", recovery_case_id)
        raise
    finally:
        db.close()