"""
PaymentGateway: the boundary between "decide to retry a payment" and
"actually call an external payment API to do it".

Why this boundary exists: Razorpay Test Mode does not offer a documented,
safe, generic "retry this failed payment" API call -- a retry in
Razorpay's model is a NEW payment attempt (usually initiated from the
customer's side via a fresh Checkout session or a payment link), not a
server-side "retry" verb on the original failed payment. Building a fake
one would mean inventing behavior Razorpay doesn't document, which the
project's ground rules explicitly forbid.

So for Phase 2:
  - RazorpayPaymentGateway.retry_payment() creates a Razorpay Payment
    Link for the failed order/amount via the documented Payment Links
    API, and returns "pending" -- the actual success/failure is
    determined later, by a real payment.captured/payment.failed webhook
    arriving for that new payment attempt (handled by the existing
    Phase 1 -> Phase 2 pipeline, same as any other payment). This
    gateway does NOT synchronously charge anything -- there's no
    server-initiated retry-with-saved-card flow implemented here, which
    is deliberate: that requires tokenization/saved-card setup this
    project doesn't have yet, and guessing at that API shape would risk
    real charge attempts.
  - MockPaymentGateway lets tests and local development simulate
    success / failure / repeated failure without calling Razorpay at
    all, or spending real (even test-mode) API quota.

Both implementations satisfy the same Protocol, so recovery_service and
the Celery task depend only on the interface, not on which one is
active.
"""

from dataclasses import dataclass
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetryOutcome:
    status: str  # "SUCCESS" | "FAILED" | "AWAITING_WEBHOOK"
    detail: str
    new_razorpay_payment_id: str | None = None


class PaymentGateway(Protocol):
    def retry_payment(
        self,
        *,
        razorpay_order_id: str | None,
        amount: int,
        currency: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> RetryOutcome: ...


class MockPaymentGateway:
    """
    Test/simulation gateway. Never calls any external API.

    `forced_outcomes` lets a test script a specific sequence of results
    (e.g. ["FAILED", "FAILED", "SUCCESS"]) to exercise the retry-then-
    recover flow deterministically. Without it, defaults to always
    returning SUCCESS, since most tests only care about the "happy path"
    plumbing and can override this per-test when they need otherwise.
    """

    def __init__(self, forced_outcomes: list[str] | None = None):
        self._forced_outcomes = list(forced_outcomes) if forced_outcomes else None
        self._call_count = 0

    def retry_payment(
        self,
        *,
        razorpay_order_id: str | None,
        amount: int,
        currency: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> RetryOutcome:
        if self._forced_outcomes is not None:
            index = min(self._call_count, len(self._forced_outcomes) - 1)
            status = self._forced_outcomes[index]
        else:
            status = "SUCCESS"
        self._call_count += 1

        return RetryOutcome(
            status=status,
            detail=f"[mock gateway] simulated {status.lower()} for order {razorpay_order_id}",
            new_razorpay_payment_id=f"pay_MOCK{self._call_count:06d}" if status == "SUCCESS" else None,
        )


class RazorpayPaymentGateway:
    """
    Real-ish Razorpay gateway using Razorpay Test Mode.

    Creates a Payment Link for the failed order's amount via Razorpay's
    documented Payment Links API (razorpay.payment_link.create). This is
    a genuinely safe operation in Test Mode: it does not move money by
    itself -- it generates a link that would need to be paid (by a
    customer, in a browser) to actually capture funds. We return PENDING
    because the outcome isn't known synchronously; it's determined later
    by an actual payment.captured or payment.failed webhook for whatever
    payment_id gets created against that link, which flows back through
    the existing Phase 1 -> Phase 2 pipeline exactly like any other
    payment event.

    This class deliberately does NOT attempt a server-side charge retry
    using stored card details -- Razorpay requires card tokenization for
    that (a separate, more involved integration this project doesn't
    have set up), and building an untested guess at that flow risks
    incorrect, unsafe payment code. If/when that's needed, it belongs in
    its own reviewed change, not bundled into this phase.
    """

    def __init__(self) -> None:
        import razorpay  # local import: keep the SDK dependency scoped to here

        settings = get_settings()
        self._client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        if not settings.RAZORPAY_KEY_ID.startswith("rzp_test_"):
            # Not a hard failure (an operator's key naming isn't something
            # we should assume total control over) but this is exactly the
            # kind of accidental-real-money-operation the project's safety
            # requirement calls out. Surface it loudly.
            logger.warning(
                "RazorpayPaymentGateway initialized with a key ID that does not "
                "look like a Test Mode key (expected prefix 'rzp_test_'). "
                "Refusing to proceed to avoid risking a live payment operation."
            )
            raise RuntimeError(
                "RazorpayPaymentGateway requires a Razorpay TEST MODE key "
                "(RAZORPAY_KEY_ID must start with 'rzp_test_')."
            )

    def retry_payment(
        self,
        *,
        razorpay_order_id: str | None,
        amount: int,
        currency: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> RetryOutcome:
        try:
            link = self._client.payment_link.create(
                {
                    "amount": amount,
                    "currency": currency,
                    "description": f"Payment retry for order {razorpay_order_id or 'unknown'}",
                    "customer": {
                        "contact": customer_contact or "",
                        "email": customer_email or "",
                    },
                    "notify": {"sms": bool(customer_contact), "email": bool(customer_email)},
                }
            )
        except Exception as exc:  # Razorpay SDK raises its own error types
            logger.warning("Failed to create Razorpay payment link for retry: %s", exc)
            return RetryOutcome(status="FAILED", detail=f"payment link creation failed: {exc}")

        return RetryOutcome(
            status="AWAITING_WEBHOOK",
            detail=f"payment link created: {link.get('short_url', '<no url>')}",
        )
