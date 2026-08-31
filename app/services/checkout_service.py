"""Standard Checkout orchestration built on the existing payment model."""

from datetime import datetime, timezone
from decimal import Decimal, ROUND_HALF_UP
from secrets import token_hex

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.payment import Payment
from app.services.payment_gateway import CheckoutOrderResult, PaymentGateway


class CheckoutOrderCreationError(Exception):
    """Raised when Razorpay cannot create a Standard Checkout Order."""


class UnknownCheckoutOrderError(Exception):
    """Raised when a browser submits an order this service did not create."""


class CheckoutOrderStateError(Exception):
    """Raised when a Checkout payment conflicts with persisted state."""


def rupees_to_paise(amount_rupees: Decimal) -> int:
    """Convert an API amount precisely; float values are never used for money."""
    return int((amount_rupees * 100).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def create_checkout_order(
    db: Session, gateway: PaymentGateway, *, amount_rupees: Decimal
) -> Payment:
    amount = rupees_to_paise(amount_rupees)
    if amount <= 0:
        raise ValueError("Amount must be greater than zero")

    # Razorpay receipts are merchant references, not customer input.
    receipt = f"checkout_{token_hex(12)}"
    result: CheckoutOrderResult = gateway.create_checkout_order(
        amount=amount, currency="INR", receipt=receipt
    )
    if (
        result.status != "created"
        or not result.razorpay_order_id
        or result.amount != amount
        or result.currency != "INR"
    ):
        raise CheckoutOrderCreationError(result.detail)

    # Payment requires a Razorpay payment id. This placeholder is internal-only
    # and is replaced with the real pay_* id after signature verification or a webhook.
    payment = Payment(
        razorpay_payment_id=f"checkout_{token_hex(16)}",
        razorpay_order_id=result.razorpay_order_id,
        amount=amount,
        currency="INR",
        status="PENDING",
        razorpay_created_at=result.created_at or datetime.now(timezone.utc),
    )
    db.add(payment)
    db.flush()
    return payment


def find_checkout_payment(db: Session, *, razorpay_order_id: str) -> Payment:
    payment = db.scalars(
        select(Payment).where(Payment.razorpay_order_id == razorpay_order_id)
    ).first()
    if payment is None or not payment.razorpay_payment_id.startswith("checkout_"):
        # A verified payment may already have its real ID after an early webhook.
        if payment is not None:
            return payment
        raise UnknownCheckoutOrderError("Unknown Standard Checkout order")
    return payment


def record_verified_checkout_payment(
    db: Session, *, order_id: str, payment_id: str
) -> Payment:
    payment = find_checkout_payment(db, razorpay_order_id=order_id)
    if payment.razorpay_payment_id == payment_id:
        return payment
    if payment.status != "PENDING":
        raise CheckoutOrderStateError("Checkout payment is no longer pending")

    existing = db.scalars(
        select(Payment).where(Payment.razorpay_payment_id == payment_id)
    ).first()
    if existing is not None and existing.id != payment.id:
        raise CheckoutOrderStateError("Payment ID belongs to another order")

    payment.razorpay_payment_id = payment_id
    db.flush()
    return payment
