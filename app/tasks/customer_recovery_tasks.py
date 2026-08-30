"""
Celery task: run customer-assisted recovery for one AWAITING_CUSTOMER
recovery case.

    RecoveryCase (AWAITING_CUSTOMER)
          |
    this task
          |
    customer_recovery_service.start_customer_recovery()
      -> create_payment_link() (idempotent)
      -> send_recovery_email() (idempotent)

One task covers both steps (rather than two separate tasks per the
prompt's example names) because they're tightly sequential -- the email
needs the link -- and splitting them would just add a second Celery
hop for no behavioral benefit, which the project brief's "do not
over-engineer" explicitly warns against.

Unlike recovery_tasks.execute_recovery_action (which disables Celery
retries because the business-level retry policy handles failed retry
*payments*), this task DOES use Celery's own retry: a failed Razorpay/
SMTP call here is a transient infrastructure failure, not a business
decision, and the idempotency checks in customer_recovery_service (partial
unique indexes + active-status checks) make a retry safe.
"""

from app.core.logging import configure_logging, get_logger
from app.db.session import SessionLocal
from app.models.payment import Payment
from app.models.recovery_case import RecoveryCase
from app.services import customer_recovery_service, recovery_service
from app.services.email_provider import get_email_provider
from app.services.payment_gateway import PaymentGateway, RazorpayPaymentGateway
from app.tasks.celery_app import celery_app

configure_logging()
logger = get_logger(__name__)


def _get_gateway() -> PaymentGateway:
    """Mirrors recovery_tasks._get_gateway; tests monkeypatch this directly."""
    return RazorpayPaymentGateway()


@celery_app.task(
    name="app.tasks.customer_recovery_tasks.run_customer_recovery",
    bind=True,
    max_retries=3,
    default_retry_delay=60,
)
def run_customer_recovery(self, case_id: int) -> str:
    db = SessionLocal()
    try:
        case = db.get(RecoveryCase, case_id)
        if case is None:
            logger.warning("run_customer_recovery: recovery_case_id=%s not found, skipping", case_id)
            return "skipped: not found"

        if case.status != "AWAITING_CUSTOMER":
            # Already resolved (e.g. RECOVERED via an unrelated webhook,
            # or CANCELLED) before this task ran -- nothing to do.
            logger.info(
                "run_customer_recovery: recovery_case_id=%s status=%s "
                "(not AWAITING_CUSTOMER), skipping",
                case_id, case.status,
            )
            return f"skipped: status={case.status}"

        payment = db.get(Payment, case.payment_id)

        gateway = _get_gateway()
        email_provider = get_email_provider()

        customer_recovery_service.start_customer_recovery(
            db, case, payment, gateway, email_provider
        )
        db.commit()
        return "done"

    except customer_recovery_service.NoCustomerEmailError:
        # Not a transient failure -- retrying won't produce an email
        # address. The payment link (if created before this was raised)
        # stays valid; just log and stop rather than retrying forever.
        db.commit()
        logger.warning(
            "run_customer_recovery: recovery_case_id=%s has no customer email; "
            "payment link created but email not sent",
            case_id,
        )
        return "skipped: no customer email"

    except customer_recovery_service.PaymentLinkProviderError as exc:
        db.rollback()
        logger.warning(
            "run_customer_recovery: recovery_case_id=%s payment link creation failed: %s",
            case_id, exc,
        )
        raise self.retry(exc=exc)

    except Exception:
        db.rollback()
        logger.exception("run_customer_recovery: unexpected error for recovery_case_id=%s", case_id)
        raise
    finally:
        db.close()


@celery_app.task(
    name="app.tasks.customer_recovery_tasks.resolve_unmatched_capture",
    bind=True,
    max_retries=5,
    default_retry_delay=30,
)
def resolve_unmatched_capture(self, payment_id: int) -> str:
    """
    Fallback correlation for a payment.captured event that the same-order
    match (payment_service._find_prior_failed_payment_on_order, unchanged)
    found nothing for. Enqueued from webhook_service only in that "no
    match" case -- see recovery_service.resolve_via_payment_link for the
    actual matching logic and why it's bounded/safe.

    Kept out of the webhook request path deliberately (per project
    convention: the route/webhook_service layer stays thin, external-API
    work happens here) so a slow or flaky Razorpay call never blocks
    webhook acknowledgement or risks Razorpay's own delivery retries
    piling up.
    """
    db = SessionLocal()
    try:
        payment = db.get(Payment, payment_id)
        if payment is None:
            logger.warning("resolve_unmatched_capture: payment_id=%s not found, skipping", payment_id)
            return "skipped: not found"

        if payment.retried_from_payment_id is not None:
            # Already resolved (this task's own earlier attempt succeeded
            # but something downstream retried it, or another path beat
            # us to it) -- idempotent no-op rather than re-resolving.
            logger.info(
                "resolve_unmatched_capture: payment_id=%s already linked to "
                "payment_id=%s, skipping",
                payment_id, payment.retried_from_payment_id,
            )
            return "skipped: already resolved"

        gateway = _get_gateway()
        result = recovery_service.resolve_via_payment_link(db, payment, gateway)

        if result.status == "matched":
            recovery_service.on_payment_captured_via_retry(db, result.resolved_payment)
            db.commit()
            return "matched"

        if result.status == "retry":
            # At least one candidate's Razorpay check errored -- we don't
            # know yet, so retry rather than conclude "not matched".
            # Nothing was mutated on this path, so a plain rollback is
            # sufficient before Celery's own retry/backoff.
            db.rollback()
            raise self.retry()

        db.commit()  # no-op commit; nothing was mutated for "not_matched"
        return "not_matched"

    except Exception:
        db.rollback()
        logger.exception("resolve_unmatched_capture: unexpected error for payment_id=%s", payment_id)
        raise
    finally:
        db.close()