"""
Razorpay webhook endpoint.

    POST /api/v1/webhooks/razorpay

Flow:
    1. Read the RAW request body (bytes). Signature verification depends
       on the exact bytes Razorpay sent -- not a re-serialized version of
       parsed JSON. This is why we use `await request.body()` instead of
       a Pydantic model as the route parameter; FastAPI would parse JSON
       for us, but we need the raw bytes first.
    2. Read the `X-Razorpay-Signature` header.
    3. Verify the signature (app/services/razorpay_client.py). Invalid or
       missing signature -> reject with 400, do not process.
    4. Parse the (now-trusted) body into our Pydantic schema.
    5. Read the `x-razorpay-event-id` header -- this is what idempotency
       is keyed on.
    6. Delegate to the service layer (app/services/webhook_service.py) to
       check for duplicates and process/store the event.

Error handling:
    - Missing/invalid signature       -> 400, generic message, no leak of
                                          what the "correct" signature is
    - Malformed JSON / schema mismatch -> 400, generic message
    - Unexpected internal error        -> 500, generic message, full
                                          detail only in server-side logs

We always return *some* 2xx/4xx response rather than letting exceptions
propagate as raw 500s with stack traces, because Razorpay will retry
failed deliveries -- we want retries to happen for real transient
failures (e.g. a DB outage), not for a payload we'll never be able to
process (e.g. a permanently malformed body), which would just retry
forever.
"""

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.core.config import Settings, get_settings
from app.core.logging import get_logger
from app.db.session import get_db
from app.schemas.webhook import RazorpayWebhookEvent, WebhookAckResponse
from app.services.razorpay_client import WebhookSignatureError, verify_webhook_signature
from app.services.webhook_service import handle_razorpay_webhook

logger = get_logger(__name__)

router = APIRouter(prefix="/webhooks", tags=["webhooks"])


@router.post(
    "/razorpay",
    response_model=WebhookAckResponse,
    status_code=status.HTTP_200_OK,
)
async def receive_razorpay_webhook(
    request: Request,
    x_razorpay_signature: str = Header(default="", alias="X-Razorpay-Signature"),
    x_razorpay_event_id: str = Header(default="", alias="X-Razorpay-Event-Id"),
    settings: Settings = Depends(get_settings),
    db: Session = Depends(get_db),
) -> WebhookAckResponse:
    raw_body = await request.body()

    # --- 1. Signature validation ---
    try:
        verify_webhook_signature(
            raw_body=raw_body,
            received_signature=x_razorpay_signature,
            webhook_secret=settings.RAZORPAY_WEBHOOK_SECRET,
        )
    except WebhookSignatureError:
        logger.warning(
            "Rejected webhook: invalid signature (event_id header=%s)",
            x_razorpay_event_id or "<missing>",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid webhook signature",
        ) from None

    # --- 2. Event ID presence (required for idempotency) ---
    if not x_razorpay_event_id:
        logger.warning("Rejected webhook: missing X-Razorpay-Event-Id header")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing X-Razorpay-Event-Id header",
        )

    # --- 3. Parse payload (only after signature is trusted) ---
    try:
        event = RazorpayWebhookEvent.model_validate_json(raw_body)
    except ValidationError:
        logger.warning(
            "Rejected webhook: malformed payload (event_id=%s)",
            x_razorpay_event_id,
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Malformed webhook payload",
        ) from None

    # --- 4. Delegate to service layer ---
    try:
        result = handle_razorpay_webhook(db=db, event_id=x_razorpay_event_id, event=event)
    except Exception:
        logger.exception(
            "Unexpected error processing webhook event_id=%s event_type=%s",
            x_razorpay_event_id,
            event.event,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Internal error processing webhook",
        ) from None

    return WebhookAckResponse(
        status=result.status,  # type: ignore[arg-type]
        event_type=result.event_type,
        event_id=result.event_id,
        detail=result.detail,
    )
