"""
Celery task: execute a single RecoveryAction.

    Redis / Celery
          |
    Background worker (this module)
          |
    Execute recovery action (call the PaymentGateway)
          |
    Record result (recovery_service.record_action_result)
          |
    RECOVERED | schedule next attempt | EXHAUSTED

Only RETRY_PAYMENT actions are ever enqueued here (see
recovery_service.AUTOMATICALLY_EXECUTED_ACTION_TYPES), so this task
doesn't need to branch on action_type today -- if a later phase
auto-executes other action types, add that branching then.
"""

from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.payment import Payment
from app.models.recovery_action import InvalidRecoveryActionTransition, RecoveryAction
from app.models.recovery_case import RecoveryCase
from app.services import recovery_service
from app.services.payment_gateway import PaymentGateway, RazorpayPaymentGateway
from app.tasks.celery_app import celery_app

configure_logging()
logger = get_logger(__name__)


def _get_gateway() -> PaymentGateway:
    """
    Select which gateway implementation to use.

    Real Razorpay Test Mode calls only happen if RAZORPAY_KEY_ID is a
    genuine rzp_test_ key (RazorpayPaymentGateway enforces this itself
    and refuses to construct otherwise -- see payment_gateway.py). Tests
    monkeypatch this function directly rather than relying on env vars,
    so they never depend on Razorpay credentials being present at all.
    """
    return RazorpayPaymentGateway()


@celery_app.task(name="app.tasks.recovery_tasks.execute_recovery_action", bind=True, max_retries=0)
def execute_recovery_action(self, action_id: int) -> str:
    """
    Execute the RecoveryAction with the given id.

    max_retries=0: Celery-level task retries are disabled deliberately.
    A failed *retry payment* is not a task execution failure -- it's an
    expected outcome that record_action_result() handles by scheduling
    the NEXT attempt per the retry policy, at the policy's delay, not
    Celery's own backoff. Letting Celery also retry the task itself
    would double-schedule attempts.
    """
    db = SessionLocal()
    try:
        action = db.get(RecoveryAction, action_id)
        if action is None:
            logger.warning("execute_recovery_action: action_id=%s not found, skipping", action_id)
            return "skipped: not found"

        if action.status != "PENDING":
            # Already handled (e.g. cancelled because the payment was
            # separately resolved via a webhook before this task's ETA
            # arrived -- see recovery_service.on_payment_captured_via_retry).
            logger.info(
                "execute_recovery_action: action_id=%s status=%s (not PENDING), skipping",
                action_id,
                action.status,
            )
            return f"skipped: status={action.status}"

        try:
            action.transition_to("PROCESSING")
        except InvalidRecoveryActionTransition:
            # A webhook resolved this action (e.g. cancelled it) in the
            # instant between the status check above and this line --
            # a narrow but real race. Nothing to do: the webhook path
            # already reached a valid terminal state for it.
            db.rollback()
            logger.info(
                "execute_recovery_action: action_id=%s was resolved by another "
                "path (e.g. a webhook) just before this task could start "
                "processing it; skipping",
                action_id,
            )
            return "skipped: resolved concurrently before processing"
        db.flush()

        case = db.get(RecoveryCase, action.recovery_case_id)
        payment = db.get(Payment, case.payment_id)

        gateway = _get_gateway()
        outcome = gateway.retry_payment(
            razorpay_order_id=payment.razorpay_order_id,
            amount=payment.amount,
            currency=payment.currency,
            customer_contact=payment.customer_contact,
            customer_email=payment.customer_email,
        )

        logger.info(
            "recovery_action_id=%s retry outcome=%s detail=%s",
            action_id,
            outcome.status,
            outcome.detail,
        )

        # The gateway call above is a real network round-trip (creating a
        # Razorpay Payment Link typically takes a couple of seconds). In
        # that window, a payment.captured webhook for an EARLIER attempt
        # on the same order can arrive and resolve this action out from
        # under us -- recovery_service.on_payment_captured_via_retry()
        # cancels any PENDING/PROCESSING action on a case it resolves.
        # Re-read the action's current status before writing anything
        # further, rather than trusting the in-memory object we loaded
        # before the network call.
        db.refresh(action)
        if action.status != "PROCESSING":
            logger.info(
                "recovery_action_id=%s was resolved concurrently (now status=%s) "
                "while the gateway call was in flight; discarding this task's "
                "outcome (%s) rather than overwriting the concurrent result",
                action_id,
                action.status,
                outcome.status,
            )
            db.rollback()
            return f"skipped: resolved concurrently, now status={action.status}"

        if outcome.status == "AWAITING_WEBHOOK":
            # Leave the action in PROCESSING. Its resolution will come
            # from a future payment.captured/payment.failed webhook for
            # the new payment attempt, handled by the normal Phase 1/2
            # pipeline (payment_service's retry-link detection), which
            # calls recovery_service.on_payment_captured_via_retry ->
            # marks this case RECOVERED and cancels this (already-
            # PROCESSING) action's siblings. We still mark payment
            # RETRYING here so its status reflects reality in the
            # meantime.
            if payment.status == "FAILED":
                payment.transition_to("RETRYING")
            db.commit()
            return "awaiting_webhook"

        succeeded = outcome.status == "SUCCESS"
        if succeeded and payment.status in ("FAILED", "RETRYING"):
            payment.transition_to("SUCCESS")

        recovery_service.record_action_result(
            db, action, succeeded=succeeded, detail=outcome.detail
        )
        db.commit()
        return outcome.status

    except Exception:
        db.rollback()
        logger.exception("execute_recovery_action: unexpected error for action_id=%s", action_id)
        raise
    finally:
        db.close()