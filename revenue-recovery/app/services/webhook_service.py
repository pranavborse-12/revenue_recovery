"""
Webhook business logic.

This is deliberately separate from app/api/routes/webhooks.py (HTTP
concerns: status codes, request/response objects) and from
app/services/razorpay_client.py (Razorpay-specific signature mechanics).
This module answers one question: "given a verified, parsed event, what
do we do with it?"

The idempotency flow, per the project brief:

    Webhook arrives
          |
    Have we processed this event already?
          |
       +--+--+
      YES    NO
       |      |
       v      v
    Ignore   Process

"Have we processed this event already?" is answered by checking whether
a WebhookEvent row with this (provider, event_id) already exists. We rely
on Razorpay's `x-razorpay-event-id` header, which their documentation
states is unique per event
(https://razorpay.com/docs/webhooks/validate-test/#idempotency).

We do NOT try to deduplicate based on payload content (e.g. payment ID +
status) -- that's a much fuzzier problem (the same payment can
legitimately produce multiple *different* events, like failed-then-
captured on a UPI retry) and is out of scope for Phase 1's basic
idempotency mechanism.

Payment-Link correlation fix (this debugging session): the same-order
match in payment_service is unchanged and still runs first. Only when it
finds nothing, and only for payment.captured, do we hand off to a
bounded Celery-based fallback (recovery_service.resolve_via_payment_link,
run via app.tasks.customer_recovery_tasks.resolve_unmatched_capture) --
see that task's docstring for why this isn't done inline here.
"""

from dataclasses import dataclass

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.logging import get_logger
from app.models.webhook_event import WebhookEvent
from app.schemas.webhook import SUPPORTED_EVENT_TYPES, RazorpayWebhookEvent
from app.services import payment_service, recovery_service

logger = get_logger(__name__)


@dataclass(frozen=True)
class WebhookHandlingResult:
    status: str  # "processed" | "ignored_duplicate" | "acknowledged" | "ignored_unsupported"
    event_type: str
    event_id: str
    detail: str | None = None


def handle_razorpay_webhook(
    db: Session,
    event_id: str,
    event: RazorpayWebhookEvent,
) -> WebhookHandlingResult:
    """
    Process a single, already-signature-verified Razorpay webhook event.

    This function is intentionally synchronous and does one unit of work
    per call: check for a duplicate, then either skip or record+process.
    It commits its own transaction so that callers (the route handler)
    don't need to know about session management details.
    """
    existing = (
        db.query(WebhookEvent)
        .filter(
            WebhookEvent.provider == "razorpay",
            WebhookEvent.event_id == event_id,
        )
        .first()
    )
    if existing is not None:
        logger.info(
            "Ignoring duplicate webhook event_id=%s event_type=%s "
            "(already recorded at %s with status=%s)",
            event_id,
            event.event,
            existing.received_at,
            existing.status,
        )
        return WebhookHandlingResult(
            status="ignored_duplicate",
            event_type=event.event,
            event_id=event_id,
            detail="Event already processed",
        )

    is_supported = event.event in SUPPORTED_EVENT_TYPES

    db_event = WebhookEvent(
        provider="razorpay",
        event_id=event_id,
        event_type=event.event,
        payload=event.model_dump(mode="json"),
        status="received",
    )
    db.add(db_event)

    try:
        # Flush (not commit yet) so the UniqueConstraint on
        # (provider, event_id) fires here if a race condition let two
        # requests for the same event both pass the .first() check above.
        # This is the database-level backstop for idempotency.
        db.flush()
    except IntegrityError:
        db.rollback()
        logger.info(
            "Duplicate webhook event_id=%s detected at insert time "
            "(concurrent delivery)",
            event_id,
        )
        return WebhookHandlingResult(
            status="ignored_duplicate",
            event_type=event.event,
            event_id=event_id,
            detail="Event already processed (race detected at insert)",
        )

    if not is_supported:
        db_event.status = "acknowledged"
        db.commit()
        logger.info(
            "Acknowledged unsupported event_id=%s event_type=%s "
            "(no handler for this event type in Phase 1)",
            event_id,
            event.event,
        )
        return WebhookHandlingResult(
            status="ignored_unsupported",
            event_type=event.event,
            event_id=event_id,
            detail=f"Event type '{event.event}' is not processed in this phase",
        )

    _log_event_summary(event)
    _run_payment_recovery_pipeline(db, event)

    from datetime import datetime, timezone

    db_event.status = "processed"
    db_event.processed_at = datetime.now(timezone.utc)
    db.commit()

    return WebhookHandlingResult(
        status="processed",
        event_type=event.event,
        event_id=event_id,
    )


def _run_payment_recovery_pipeline(db: Session, event: RazorpayWebhookEvent) -> None:
    """
    Phase 2: derive Payment state from this event, and drive the
    recovery workflow off of it.

    Runs in the SAME transaction as the WebhookEvent write (no commit
    happens until handle_razorpay_webhook's final db.commit() below) --
    this means a failure anywhere in payment/recovery processing rolls
    back the WebhookEvent's status change too, so we never end up with
    an event marked "processed" whose derived state didn't actually get
    written. The event itself was already flushed (and is therefore
    protected by its own unique constraint against duplicate delivery)
    before this function is called.
    """
    if event.payload.payment is None:
        return
    entity = event.payload.payment.entity

    result = payment_service.upsert_payment_from_event(db, event.event, entity)

    if result.newly_failed:
        recovery_service.on_payment_failed(db, result.payment)

    if result.linked_retry_of is not None:
        recovery_service.on_payment_captured_via_retry(db, result.linked_retry_of)
    elif event.event == "payment.captured":
        # Same-order correlation found nothing. Before concluding this is
        # just an ordinary, unrelated payment, check whether it actually
        # resolves an AWAITING_CUSTOMER case's Payment Link -- Razorpay
        # mints a brand-new order per Payment Link, so the same-order
        # check can never see that relationship (confirmed via live
        # debugging; see recovery_service.resolve_via_payment_link).
        # Deliberately NOT done inline here: it may call Razorpay, and
        # this function runs inside the webhook's own DB transaction --
        # an external call here would risk delaying/failing webhook
        # acknowledgement. Handed to Celery instead, same as every other
        # external-API step in this project.
        from app.tasks.customer_recovery_tasks import resolve_unmatched_capture

        db.flush()  # ensure result.payment.id is assigned before the task can look it up
        resolve_unmatched_capture.apply_async(args=[result.payment.id], countdown=0)


def _log_event_summary(event: RazorpayWebhookEvent) -> None:
    """
    Log the useful, non-sensitive fields of a supported event.

    We deliberately log payment_id/order_id/amount/status/error_code, but
    NOT email or contact (customer PII) at info level -- Phase 1 doesn't
    need customer PII in logs, and keeping it out reduces the blast
    radius if logs are ever exposed.
    """
    if event.payload.payment is None:
        return
    entity = event.payload.payment.entity
    logger.info(
        "Processed %s | payment_id=%s order_id=%s amount=%d currency=%s "
        "status=%s error_code=%s",
        event.event,
        entity.id,
        entity.order_id,
        entity.amount,
        entity.currency,
        entity.status,
        entity.error_code or "-",
    )