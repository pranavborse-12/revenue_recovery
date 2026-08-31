"""
Celery task: request_ai_recommendation.

    RecoveryCase (a decision point was just reached)
          |
    this task
          |
    recovery_context.build_recovery_context()
          |
    ai_recovery_service.recommend()  -- None on ANY failure
          |
    recovery_service.validate_ai_recommendation()  -- policy check
          |
    AIRecoveryDecision row stored

Audit-only: this task never writes to RecoveryCase, RecoveryAction, or
PaymentLink. Its only side effect is inserting one row into
ai_recovery_decisions. A bug here cannot corrupt recovery state.

Celery-level retries are enabled (unlike execute_recovery_action) because
a failure here is purely infrastructural (AI provider hiccup) -- there's
no business-level "policy" governing when to retry an audit computation,
unlike a real payment retry.
"""

from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.ai_recovery_decision import AIRecoveryDecision
from app.models.recovery_case import RecoveryCase
from app.services import recovery_context, recovery_service
from app.services.ai_recovery_service import get_ai_recovery_service
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

        service = get_ai_recovery_service()
        if service is None:
            return "skipped: AI disabled or unconfigured"

        context = recovery_context.build_recovery_context(db, case)
        recommendation = service.recommend(context)
        if recommendation is None:
            logger.info("recovery_case_id=%s: no usable AI recommendation", case.id)
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
                model=service._model,
                accepted=accepted,
                rejection_reason=rejection_reason,
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