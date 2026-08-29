"""
RecoveryService: decides what happens after a payment failure, and owns
the RecoveryCase / RecoveryAction lifecycle.

    Payment Failure
          |
    Failure Classification (failure_classifier.py)
          |
    Recovery Strategy (this module: STRATEGY_BY_CATEGORY)
          |
    RecoveryCase created/updated + RecoveryAction scheduled

Called from webhook_service.py right after payment_service.py updates
Payment state. Two entry points matter:

  - on_payment_failed(): a payment just moved into FAILED. Open (or
    reuse) a recovery case, pick a strategy, schedule the first action.
  - on_payment_captured_via_retry(): a payment.captured event resolved a
    prior failed payment (payment_service already found the link). If
    that prior payment has an open recovery case, mark it RECOVERED and
    cancel any pending actions -- we don't need to keep retrying
    something that already succeeded.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.core.retry_policy import get_retry_policy
from app.models.payment import Payment
from app.models.recovery_action import RecoveryAction
from app.models.recovery_case import TERMINAL_RECOVERY_CASE_STATUSES, RecoveryCase

logger = get_logger(__name__)

# Deterministic strategy selection. Kept as a plain dict, not a class
# hierarchy -- there's no behavior variation per strategy yet beyond
# "which action_type to schedule", so a dict is the simplest thing that
# is actually correct. If a later phase needs strategy-specific logic
# (e.g. different retry policies per category), promote this to
# something richer then, not preemptively now.
STRATEGY_BY_CATEGORY: dict[str, str] = {
    "INSUFFICIENT_FUNDS": "RETRY_PAYMENT",
    "TEMPORARY_NETWORK_ERROR": "RETRY_PAYMENT",
    "BANK_DECLINED": "RETRY_PAYMENT",
    "PAYMENT_METHOD_EXPIRED": "REQUEST_PAYMENT_METHOD_UPDATE",
    "PAYMENT_METHOD_INVALID": "REQUEST_PAYMENT_METHOD_UPDATE",
    "UNKNOWN": "MANUAL_REVIEW",
}

# Only RETRY_PAYMENT is actually scheduled/executed by Celery in Phase 2
# (per the project brief: "prioritize RETRY_PAYMENT ... do not implement
# complex notification integrations unless genuinely required"). Other
# strategies still create a case+action row (for visibility/stats) but
# are left in PENDING for a human/future phase to act on.
AUTOMATICALLY_EXECUTED_ACTION_TYPES = {"RETRY_PAYMENT"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


@dataclass(frozen=True)
class RecoveryDecision:
    recovery_case: RecoveryCase
    recovery_action: RecoveryAction | None
    is_new_case: bool


def on_payment_failed(db: Session, payment: Payment) -> RecoveryDecision:
    """
    Handle a payment that just transitioned into FAILED.

    Idempotency: if payment already has a non-terminal RecoveryCase
    (OPEN or IN_PROGRESS), we reuse it instead of creating a second one
    -- this is the primary defense against duplicate webhook delivery
    creating duplicate recovery tracks. The database-level partial
    unique index (see the migration) backstops this against races the
    same way Phase 1's WebhookEvent unique constraint backstops event
    dedup.
    """
    existing_case = db.scalars(
        select(RecoveryCase).where(
            RecoveryCase.payment_id == payment.id,
            RecoveryCase.status.not_in(TERMINAL_RECOVERY_CASE_STATUSES),
        )
    ).first()

    if existing_case is not None:
        logger.info(
            "Reusing existing open recovery_case_id=%s for payment_id=%s "
            "(status=%s) -- not creating a duplicate",
            existing_case.id,
            payment.id,
            existing_case.status,
        )
        return RecoveryDecision(
            recovery_case=existing_case, recovery_action=None, is_new_case=False
        )

    category = payment.failure_category or "UNKNOWN"
    strategy = STRATEGY_BY_CATEGORY.get(category, "MANUAL_REVIEW")

    case = RecoveryCase(
        payment_id=payment.id,
        failure_category=category,
        amount=payment.amount,
        status="OPEN",
        current_strategy=strategy,
    )
    db.add(case)
    db.flush()

    logger.info(
        "Opened recovery_case_id=%s for payment_id=%s category=%s strategy=%s",
        case.id,
        payment.id,
        category,
        strategy,
    )

    action = _schedule_next_action(db, case, strategy)
    return RecoveryDecision(recovery_case=case, recovery_action=action, is_new_case=True)


def on_payment_captured_via_retry(db: Session, resolved_payment: Payment) -> RecoveryCase | None:
    """
    A payment.captured event linked back to `resolved_payment` (a prior
    FAILED/RETRYING payment on the same order). If that payment has an
    open recovery case, mark it RECOVERED and cancel any still-pending
    actions -- the money came in, no further retries needed.
    """
    case = db.scalars(
        select(RecoveryCase).where(
            RecoveryCase.payment_id == resolved_payment.id,
            RecoveryCase.status.not_in(TERMINAL_RECOVERY_CASE_STATUSES),
        )
    ).first()
    if case is None:
        return None

    for action in db.scalars(
        select(RecoveryAction).where(
            RecoveryAction.recovery_case_id == case.id,
            RecoveryAction.status.in_(("PENDING", "PROCESSING")),
        )
    ):
        action.transition_to("CANCELLED")

    if case.status == "OPEN":
        case.transition_to("IN_PROGRESS")
    case.transition_to("RECOVERED")

    logger.info(
        "recovery_case_id=%s RECOVERED via retry resolving prior payment_id=%s",
        case.id,
        resolved_payment.id,
    )
    return case


def record_action_result(
    db: Session, action: RecoveryAction, *, succeeded: bool, detail: str
) -> RecoveryCase:
    """
    Record the outcome of an executed RecoveryAction (called by the
    Celery task after actually attempting the retry) and advance the
    parent RecoveryCase accordingly:

        succeeded  -> case RECOVERED
        failed, more attempts left -> schedule next action
        failed, attempts exhausted -> case EXHAUSTED

    Accepts the action in either PENDING or PROCESSING status: the normal
    Celery task path transitions PENDING -> PROCESSING itself before
    calling this function, but this function is also a legitimate direct
    entry point (e.g. from tests, or a future manual-resolution API) and
    shouldn't require the caller to know about that intermediate step.
    """
    if action.status == "PENDING":
        action.transition_to("PROCESSING")
    action.transition_to("SUCCESS" if succeeded else "FAILED")
    action.executed_at = _utcnow()
    action.result = detail

    case = db.get(RecoveryCase, action.recovery_case_id)
    assert case is not None  # FK guarantees this; assert documents the invariant

    if succeeded:
        case.transition_to("RECOVERED")
        logger.info("recovery_case_id=%s RECOVERED (action_id=%s succeeded)", case.id, action.id)
        return case

    policy = get_retry_policy()
    if policy.is_exhausted(case.attempt_count):
        case.transition_to("EXHAUSTED")
        logger.info(
            "recovery_case_id=%s EXHAUSTED after %d attempts",
            case.id,
            case.attempt_count,
        )
        return case

    logger.info(
        "recovery_case_id=%s action_id=%s failed (%s); scheduling next attempt",
        case.id,
        action.id,
        detail,
    )
    _schedule_next_action(db, case, case.current_strategy or "MANUAL_REVIEW")
    return case


def _schedule_next_action(db: Session, case: RecoveryCase, strategy: str) -> RecoveryAction | None:
    """
    Create the next RecoveryAction for a case and, if it's an
    automatically-executed type, enqueue it via Celery with the
    appropriate delay from the retry policy.
    """
    policy = get_retry_policy()
    next_attempt_number = case.attempt_count + 1

    if policy.is_exhausted(case.attempt_count):
        case.transition_to("EXHAUSTED")
        logger.info(
            "recovery_case_id=%s EXHAUSTED before scheduling (attempt_count=%d "
            "already at policy max=%d)",
            case.id,
            case.attempt_count,
            policy.max_attempts,
        )
        return None

    scheduled_at = policy.scheduled_at_for_attempt(next_attempt_number)

    action = RecoveryAction(
        recovery_case_id=case.id,
        action_type=strategy,
        status="PENDING",
        attempt_number=next_attempt_number,
        scheduled_at=scheduled_at,
    )
    db.add(action)
    case.attempt_count = next_attempt_number
    if case.status == "OPEN":
        case.transition_to("IN_PROGRESS")
    db.flush()

    if strategy in AUTOMATICALLY_EXECUTED_ACTION_TYPES:
        _enqueue_action(action)
    else:
        logger.info(
            "recovery_action_id=%s type=%s created but not auto-executed "
            "(requires manual/notification handling, out of Phase 2 scope)",
            action.id,
            strategy,
        )

    return action


def _enqueue_action(action: RecoveryAction, *, immediate: bool = False) -> None:
    """
    Hand the action off to Celery.

    By default, scheduled for its `scheduled_at` time (the normal retry-
    policy path). `immediate=True` dispatches it right away instead --
    used by the manual "retry now" API endpoint, which exists specifically
    to bypass the scheduled delay for demoing/testing.

    Imported locally to avoid a hard import-time dependency between
    recovery_service (pure business logic, easy to unit test) and the
    Celery app (which requires a broker URL to even construct). Tests
    that don't care about Celery dispatch monkeypatch this function via
    the app.services.recovery_service._enqueue_action name.
    """
    from app.tasks.recovery_tasks import execute_recovery_action

    if immediate:
        execute_recovery_action.apply_async(args=[action.id], countdown=0)
    else:
        execute_recovery_action.apply_async(args=[action.id], eta=action.scheduled_at)
