"""
PaymentGateway: the boundary between "decide to retry a payment" and
"actually call an external payment API to do it".

Phase 2 (unchanged): RazorpayPaymentGateway.retry_payment() creates a
Razorpay Payment Link and returns "pending" (AWAITING_WEBHOOK) -- the
actual success/failure is determined later by a real
payment.captured/payment.failed webhook, per the existing Phase 1/2
pipeline. MockPaymentGateway simulates outcomes for tests.

Phase 3 addition: create_payment_link() is the same underlying Razorpay
operation (a Payment Link), but returns the link's full identity
(id/url/expiry) instead of a bare pending/failed verdict, because
customer_recovery_service needs to persist and email that link. Both
methods share one internal helper (_call_create_payment_link) rather
than duplicating the razorpay SDK call.
"""

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol

from app.core.config import get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class RetryOutcome:
    status: str  # "SUCCESS" | "FAILED" | "AWAITING_WEBHOOK"
    detail: str
    new_razorpay_payment_id: str | None = None
    # Populated when status=="AWAITING_WEBHOOK" (a Payment Link was
    # actually created) so the caller can persist a PaymentLink row
    # instead of only having the URL embedded in `detail` text.
    razorpay_payment_link_id: str | None = None
    short_url: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class PaymentLinkResult:
    status: str  # "created" | "failed"
    detail: str
    razorpay_payment_link_id: str | None = None
    short_url: str | None = None
    expires_at: datetime | None = None


@dataclass(frozen=True)
class PaymentLinkMatchResult:
    # "matched" | "not_matched" | "error" -- "error" means we genuinely
    # couldn't ask Razorpay (network/API failure), which the caller must
    # treat differently from a confirmed non-match.
    status: str
    detail: str = ""


@dataclass(frozen=True)
class CheckoutOrderResult:
    status: str  # "created" | "failed"
    detail: str
    razorpay_order_id: str | None = None
    amount: int | None = None
    currency: str | None = None
    created_at: datetime | None = None


class PaymentGateway(Protocol):
    def create_checkout_order(
        self, *, amount: int, currency: str, receipt: str
    ) -> CheckoutOrderResult: ...

    def retry_payment(
        self,
        *,
        razorpay_order_id: str | None,
        amount: int,
        currency: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> RetryOutcome: ...

    def create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> PaymentLinkResult: ...

    def check_payment_link_paid(
        self, *, razorpay_payment_link_id: str, razorpay_payment_id: str
    ) -> PaymentLinkMatchResult:
        """
        Does this Payment Link's Razorpay-maintained payments[] list
        contain this payment_id? The only confirmed relationship between
        a Payment Link and the payment that resolved it (order_id and
        invoice_id are NOT usable here -- see payment_gateway.py's
        module docstring and recovery_service.resolve_via_payment_link
        for why).
        """
        ...


class MockPaymentGateway:
    """Test/simulation gateway. Never calls any external API."""

    def __init__(
        self,
        forced_outcomes: list[str] | None = None,
        *,
        paid_links: dict[str, str] | None = None,
        force_error: set[str] | None = None,
    ):
        self._forced_outcomes = list(forced_outcomes) if forced_outcomes else None
        self._call_count = 0
        self._link_call_count = 0
        # {razorpay_payment_link_id: razorpay_payment_id} pairs that
        # check_payment_link_paid should report as matched.
        self.paid_links = dict(paid_links) if paid_links else {}
        self.force_error = set(force_error) if force_error else set()

    def create_checkout_order(
        self, *, amount: int, currency: str, receipt: str
    ) -> CheckoutOrderResult:
        self._call_count += 1
        return CheckoutOrderResult(
            status="created",
            detail="[mock gateway] checkout order created",
            razorpay_order_id=f"order_MOCK{self._call_count:06d}",
            amount=amount,
            currency=currency,
            created_at=datetime.now(timezone.utc),
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
        if self._forced_outcomes is not None:
            index = min(self._call_count, len(self._forced_outcomes) - 1)
            status = self._forced_outcomes[index]
        else:
            status = "SUCCESS"
        self._call_count += 1

        link_kwargs = {}
        if status == "AWAITING_WEBHOOK":
            self._link_call_count += 1
            link_id = f"plink_MOCK{self._link_call_count:06d}"
            link_kwargs = {
                "razorpay_payment_link_id": link_id,
                "short_url": f"https://rzp.io/i/{link_id}",
            }

        return RetryOutcome(
            status=status,
            detail=f"[mock gateway] simulated {status.lower()} for order {razorpay_order_id}",
            new_razorpay_payment_id=f"pay_MOCK{self._call_count:06d}" if status == "SUCCESS" else None,
            **link_kwargs,
        )

    def create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> PaymentLinkResult:
        self._link_call_count += 1
        link_id = f"plink_MOCK{self._link_call_count:06d}"
        return PaymentLinkResult(
            status="created",
            detail="[mock gateway] payment link created",
            razorpay_payment_link_id=link_id,
            short_url=f"https://rzp.io/i/{link_id}",
            expires_at=None,
        )

    def check_payment_link_paid(
        self, *, razorpay_payment_link_id: str, razorpay_payment_id: str
    ) -> PaymentLinkMatchResult:
        """
        Test hook: set self.paid_links = {link_id: payment_id, ...} (or
        pass matches=... to __init__) to control which (link, payment)
        pairs report a match. Defaults to "no match" for anything not
        configured, and honors self.force_error (a set of link ids) to
        simulate a Razorpay API failure for specific candidates.
        """
        if razorpay_payment_link_id in self.force_error:
            return PaymentLinkMatchResult(status="error", detail="[mock gateway] simulated API error")
        if self.paid_links.get(razorpay_payment_link_id) == razorpay_payment_id:
            return PaymentLinkMatchResult(status="matched")
        return PaymentLinkMatchResult(status="not_matched")


class RazorpayPaymentGateway:
    """Real-ish Razorpay gateway using Razorpay Test Mode."""

    def __init__(self) -> None:
        import razorpay  # local import: keep the SDK dependency scoped to here

        settings = get_settings()
        self._client = razorpay.Client(
            auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET)
        )
        if not settings.RAZORPAY_KEY_ID.startswith("rzp_test_"):
            logger.warning(
                "RazorpayPaymentGateway initialized with a key ID that does not "
                "look like a Test Mode key (expected prefix 'rzp_test_'). "
                "Refusing to proceed to avoid risking a live payment operation."
            )
            raise RuntimeError(
                "RazorpayPaymentGateway requires a Razorpay TEST MODE key "
                "(RAZORPAY_KEY_ID must start with 'rzp_test_')."
            )

    def create_checkout_order(
        self, *, amount: int, currency: str, receipt: str
    ) -> CheckoutOrderResult:
        try:
            order = self._client.order.create(
                {"amount": amount, "currency": currency, "receipt": receipt}
            )
        except Exception as exc:  # Razorpay SDK raises provider-specific errors
            logger.warning("Failed to create Razorpay Checkout order: %s", exc)
            return CheckoutOrderResult(status="failed", detail=f"order creation failed: {exc}")

        created_at = order.get("created_at")
        return CheckoutOrderResult(
            status="created",
            detail="checkout order created",
            razorpay_order_id=order.get("id"),
            amount=order.get("amount"),
            currency=order.get("currency"),
            created_at=(
                datetime.fromtimestamp(created_at, tz=timezone.utc)
                if created_at is not None
                else datetime.now(timezone.utc)
            ),
        )

    def _call_create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> dict:
        """Shared Razorpay Payment Links API call. May raise."""
        return self._client.payment_link.create(
            {
                "amount": amount,
                "currency": currency,
                "description": description,
                "customer": {
                    "contact": customer_contact or "",
                    "email": customer_email or "",
                },
                "notify": {"sms": bool(customer_contact), "email": bool(customer_email)},
            }
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
            link = self._call_create_payment_link(
                amount=amount,
                currency=currency,
                description=f"Payment retry for order {razorpay_order_id or 'unknown'}",
                customer_contact=customer_contact,
                customer_email=customer_email,
            )
        except Exception as exc:  # Razorpay SDK raises its own error types
            logger.warning("Failed to create Razorpay payment link for retry: %s", exc)
            return RetryOutcome(status="FAILED", detail=f"payment link creation failed: {exc}")

        expire_by = link.get("expire_by")
        expires_at = (
            datetime.fromtimestamp(expire_by, tz=timezone.utc) if expire_by is not None else None
        )

        return RetryOutcome(
            status="AWAITING_WEBHOOK",
            detail=f"payment link created: {link.get('short_url', '<no url>')}",
            razorpay_payment_link_id=link.get("id"),
            short_url=link.get("short_url"),
            expires_at=expires_at,
        )

    def create_payment_link(
        self,
        *,
        amount: int,
        currency: str,
        description: str,
        customer_contact: str | None,
        customer_email: str | None,
    ) -> PaymentLinkResult:
        try:
            link = self._call_create_payment_link(
                amount=amount,
                currency=currency,
                description=description,
                customer_contact=customer_contact,
                customer_email=customer_email,
            )
        except Exception as exc:
            logger.warning("Failed to create Razorpay customer recovery payment link: %s", exc)
            return PaymentLinkResult(status="failed", detail=f"payment link creation failed: {exc}")

        expire_by = link.get("expire_by")
        expires_at = (
            datetime.fromtimestamp(expire_by, tz=timezone.utc) if expire_by is not None else None
        )

        return PaymentLinkResult(
            status="created",
            detail="payment link created",
            razorpay_payment_link_id=link["id"],
            short_url=link["short_url"],
            expires_at=expires_at,
        )

    def check_payment_link_paid(
        self, *, razorpay_payment_link_id: str, razorpay_payment_id: str
    ) -> PaymentLinkMatchResult:
        try:
            link = self._client.payment_link.fetch(razorpay_payment_link_id)
        except Exception as exc:  # network/API failure -- distinct from a confirmed non-match
            logger.warning(
                "Failed to fetch payment_link_id=%s while checking for payment_id=%s: %s",
                razorpay_payment_link_id, razorpay_payment_id, exc,
            )
            return PaymentLinkMatchResult(status="error", detail=str(exc))

        # payments[] is documented as populated only after a successful
        # capture -- confirmed empirically (see scripts/inspect_real_payment.py
        # from this debugging session). This is the one Razorpay-maintained
        # pointer from a Payment Link back to the payment that resolved it;
        # order_id and invoice_id on the payment entity are NOT usable
        # (order_id is a brand-new order Razorpay mints per link, and
        # invoice_id was confirmed null on a real captured payment).
        for entry in link.get("payments") or []:
            if entry.get("payment_id") == razorpay_payment_id:
                return PaymentLinkMatchResult(status="matched")

        return PaymentLinkMatchResult(status="not_matched")
