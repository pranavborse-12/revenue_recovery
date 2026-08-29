"""
Razorpay integration layer.

This module owns all direct interaction with Razorpay-specific mechanics
(right now: just webhook signature verification). It knows nothing about
our database, our event model, or what we do with an event once it's
verified -- that's webhook_service.py's job.

Why separate these: if Razorpay changes their SDK, or we swap to calling
their REST API directly instead of the SDK, only this file should need to
change. Business logic (idempotency, storage, logging decisions) should
never need to know *how* a signature is verified, only *whether* it was.

Signature verification, per Razorpay's documentation
(https://razorpay.com/docs/webhooks/validate-test/):

    key                = webhook_secret
    message             = webhook_body  // raw webhook request body, UNPARSED
    received_signature  = value of the X-Razorpay-Signature header
    expected_signature  = hmac_sha256(message, key)

    valid if expected_signature == received_signature

Razorpay explicitly warns: "ensure that the webhook body passed as an
argument is the raw webhook request body. Do not parse or cast the
webhook request body." This is why our route handler (see
app/api/routes/webhooks.py) reads `await request.body()` -- the raw
bytes -- and passes those bytes here, rather than passing an
already-JSON-parsed dict. HMAC signatures are computed over exact bytes;
re-serializing parsed JSON can produce different bytes (different key
ordering, spacing) and silently break verification.
"""

import hmac
import hashlib

import razorpay
from razorpay.errors import SignatureVerificationError

from app.core.logging import get_logger

logger = get_logger(__name__)


class WebhookSignatureError(Exception):
    """Raised when a webhook's signature does not match the expected value."""


def verify_webhook_signature(
    raw_body: bytes,
    received_signature: str,
    webhook_secret: str,
) -> None:
    """
    Verify a Razorpay webhook signature.

    Raises WebhookSignatureError if the signature is invalid or missing.
    Does nothing (returns None) if the signature is valid.

    We use Razorpay's official Python SDK utility
    (`razorpay.Utility.verify_webhook_signature`) as the primary
    mechanism, since it's the documented, officially supported path and
    handles the HMAC comparison safely (constant-time compare, avoiding
    timing attacks). We don't hand-roll the HMAC comparison as the
    primary path, but the module-level `_manual_hmac_sha256` function
    below documents the equivalent manual computation for transparency /
    testing.
    """
    if not received_signature:
        raise WebhookSignatureError("Missing X-Razorpay-Signature header")

    client = razorpay.Client(auth=("", ""))  # no API auth needed for this utility
    try:
        client.utility.verify_webhook_signature(
            raw_body.decode("utf-8"),
            received_signature,
            webhook_secret,
        )
    except SignatureVerificationError as exc:
        raise WebhookSignatureError(str(exc)) from exc


def _manual_hmac_sha256(raw_body: bytes, webhook_secret: str) -> str:
    """
    Manual HMAC-SHA256 computation, matching Razorpay's documented
    algorithm exactly. Not used in the request path -- kept as a
    reference implementation and used directly in tests to generate
    valid signatures for fixture payloads without depending on the SDK's
    internals.
    """
    return hmac.new(
        key=webhook_secret.encode("utf-8"),
        msg=raw_body,
        digestmod=hashlib.sha256,
    ).hexdigest()
