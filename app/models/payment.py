"""
Payment: business-level representation of a Razorpay payment.

Distinct from WebhookEvent (Phase 1): WebhookEvent is the raw, append-only
audit log of every webhook delivery. Payment is the current, mutable
business state of a single payment attempt -- "what do we currently
believe is true about pay_XXXX", derived FROM webhook events, not a
duplicate of their JSON.

One Payment row per Razorpay payment_id. Updated in place as new events
arrive for that payment_id (e.g. payment.failed, then later a separate
payment_id for a retry that succeeds -- see `retried_from_payment_id`
for how we link those).
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# Valid payment statuses and the transitions we allow between them.
# Kept intentionally small -- only what Phase 1's two event types
# (payment.captured, payment.failed) can actually produce.
#
#   PENDING -> SUCCESS
#   PENDING -> FAILED
#   FAILED  -> RETRYING   (a recovery action was scheduled)
#   RETRYING -> SUCCESS   (a retry payment was captured)
#   RETRYING -> FAILED    (a retry payment also failed)
#
# CANCELLED exists for completeness (a recovery case can be cancelled,
# which cancels the payment's recovery track) but nothing in Phase 2
# transitions a payment INTO cancelled automatically -- it's set
# explicitly by recovery_service when a case is cancelled.
VALID_PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"SUCCESS", "FAILED"},
    "FAILED": {"RETRYING", "CANCELLED"},
    "RETRYING": {"SUCCESS", "FAILED"},
    "SUCCESS": set(),  # terminal
    "CANCELLED": set(),  # terminal
}


class InvalidPaymentTransition(Exception):
    """Raised when code attempts to move a Payment to a disallowed status."""

    def __init__(self, current: str, attempted: str):
        self.current = current
        self.attempted = attempted
        super().__init__(f"Cannot transition payment from {current} to {attempted}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Payment(Base):
    __tablename__ = "payments"
    __table_args__ = (
        Index("ix_payments_order_id", "razorpay_order_id"),
        Index("ix_payments_status", "status"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # Razorpay identifiers. razorpay_payment_id is unique -- one Payment
    # row per Razorpay payment attempt.
    razorpay_payment_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # Customer identity where available. Razorpay's payment webhook
    # payload doesn't reliably include a customer_id (see schemas/webhook.py
    # for the same note in Phase 1) -- we store email/contact as the best
    # available identity signal, not a foreign key to a Customer table we
    # don't have real requirements for yet.
    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)  # smallest currency unit
    currency: Mapped[str] = mapped_column(String(8), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")

    # Failure details, populated only when status is FAILED or RETRYING
    # (i.e. the payment has failed at least once).
    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(32), nullable=True)

    # Retry-chain linkage: if this payment is itself a retry attempt that
    # succeeded after a prior payment on the SAME order failed, this
    # points at that prior Payment row. Populated by payment_service when
    # a payment.captured event arrives for an order that has a prior
    # FAILED/RETRYING payment. Nullable self-reference, not a hard FK
    # requirement -- most payments are not retries.
    retried_from_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )

    razorpay_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def transition_to(self, new_status: str) -> None:
        """
        Move this payment to new_status, enforcing VALID_PAYMENT_TRANSITIONS.

        Raises InvalidPaymentTransition if the move isn't allowed. This is
        the single choke point for status changes -- callers should never
        assign `payment.status = ...` directly, so an invalid transition
        can't accidentally corrupt state.
        """
        allowed = VALID_PAYMENT_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidPaymentTransition(self.status, new_status)
        self.status = new_status

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Payment id={self.id} razorpay_payment_id={self.razorpay_payment_id} "
            f"status={self.status} amount={self.amount}>"
        )