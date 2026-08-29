"""
Pydantic schemas for Razorpay webhook payloads.

Important distinction (per the project brief): Razorpay event ID, Payment
ID, Order ID, and Customer ID are all different identifiers:

  - Event ID:   `x-razorpay-event-id` HTTP header. Unique per webhook
                delivery attempt-set. Used for idempotency.
  - Payment ID: `payload.payment.entity.id`, e.g. "pay_DESp9bgForNoUd".
                Identifies a specific payment attempt.
  - Order ID:   `payload.payment.entity.order_id`, e.g. "order_DESoU0U4ikYA19".
                Identifies the order the payment was for. One order can
                have multiple payment attempts (e.g. a failed one
                followed by a successful retry).
  - Customer ID: Razorpay's payment payload does NOT reliably include a
                `customer_id` field on the payment entity itself in the
                base webhook payload (it appears on some payment methods'
                token/customer objects, not consistently). We do not
                invent a customer_id field. If we need robust customer
                identification in a later phase, we will fetch the
                Customer entity via the Razorpay API rather than guessing
                from the webhook payload.

These schemas model the *subset* of Razorpay's actual payload shape that
Phase 1 needs, per Razorpay's documented sample payloads
(https://razorpay.com/docs/webhooks/payments/). We intentionally use
`extra="ignore"` so that fields Razorpay adds later (or fields we don't
care about yet, like `card`, `acquirer_data`) don't break parsing -- but
we also never invent fields that aren't in Razorpay's documentation.
"""

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# Event types Phase 1 explicitly supports. Anything else is accepted
# (200 OK, so Razorpay doesn't retry it) but not processed -- see
# webhook_service.py for why "unsupported but acknowledged" is the right
# behavior rather than rejecting it.
SUPPORTED_EVENT_TYPES = {"payment.captured", "payment.failed"}


class RazorpayPaymentEntity(BaseModel):
    """
    The `payload.payment.entity` object from a Razorpay payment webhook.

    Only fields Phase 1 actually uses are declared explicitly; everything
    else Razorpay sends is ignored rather than rejected.
    """

    model_config = ConfigDict(extra="ignore")

    id: str  # Payment ID, e.g. "pay_DESp9bgForNoUd"
    order_id: str | None = None
    amount: int  # Amount in the smallest currency unit (e.g. paise for INR)
    currency: str
    status: str  # e.g. "captured", "failed", "authorized"
    method: str | None = None
    email: str | None = None
    contact: str | None = None
    error_code: str | None = None
    error_description: str | None = None
    # Razorpay's structured failure reason, distinct from error_code (which
    # is often a generic bucket like "BAD_REQUEST_ERROR" or "GATEWAY_ERROR").
    # Documented values include "insufficient_funds", "card_expired",
    # "card_declined", "bank_technical_error", "payment_timed_out", etc.
    # (https://razorpay.com/docs/errors/payments/cards/). Previously this
    # field was silently dropped by extra="ignore" -- failure_classifier.py
    # was classifying off error_description text alone, which Razorpay Test
    # Mode's synthetic failures don't always populate distinctly. error_reason
    # is the more reliable signal and is now the classifier's primary input.
    error_reason: str | None = None
    created_at: int  # Unix timestamp


class RazorpayPaymentPayload(BaseModel):
    """The `payload.payment` wrapper object."""

    model_config = ConfigDict(extra="ignore")

    entity: RazorpayPaymentEntity


class RazorpayWebhookPayload(BaseModel):
    """The `payload` object at the top level of the webhook body."""

    model_config = ConfigDict(extra="ignore")

    payment: RazorpayPaymentPayload | None = None


class RazorpayWebhookEvent(BaseModel):
    """
    The full top-level Razorpay webhook request body.

    Matches Razorpay's documented envelope:
        {
          "entity": "event",
          "account_id": "...",
          "event": "payment.captured",
          "contains": ["payment"],
          "payload": { "payment": { "entity": { ... } } },
          "created_at": 1691735748
        }
    """

    model_config = ConfigDict(extra="ignore")

    entity: Literal["event"]
    account_id: str | None = None
    event: str
    contains: list[str] = Field(default_factory=list)
    payload: RazorpayWebhookPayload
    created_at: int


class WebhookAckResponse(BaseModel):
    """What we return to Razorpay after handling a webhook request."""

    status: Literal["processed", "ignored_duplicate", "acknowledged", "ignored_unsupported"]
    event_type: str
    event_id: str | None = None
    detail: str | None = None