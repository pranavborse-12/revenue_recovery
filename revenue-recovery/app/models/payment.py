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

is_synthetic (this change): marks rows inserted directly by
scripts/seed_synthetic_history.py for historical-intelligence bootstrap
data, never created via the real webhook/payment_service path. Every
synthetic row is inserted already in a terminal Payment/RecoveryCase/
RecoveryAction state, so no live Celery task or webhook handler ever
picks one up -- is_synthetic is a clear label for humans/queries, not
itself the safety mechanism (the terminal-state-only seeding is).
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

VALID_PAYMENT_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"SUCCESS", "FAILED"},
    "FAILED": {"RETRYING", "CANCELLED"},
    "RETRYING": {"SUCCESS", "FAILED"},
    "SUCCESS": set(),
    "CANCELLED": set(),
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
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    razorpay_payment_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    razorpay_order_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    customer_email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    customer_contact: Mapped[str | None] = mapped_column(String(32), nullable=True)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")

    failure_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_description: Mapped[str | None] = mapped_column(String(512), nullable=True)
    failure_reason: Mapped[str | None] = mapped_column(String(64), nullable=True)
    failure_category: Mapped[str | None] = mapped_column(String(32), nullable=True)

    retried_from_payment_id: Mapped[int | None] = mapped_column(
        ForeignKey("payments.id", ondelete="SET NULL"), nullable=True
    )

    # Phase 4 addition: see module docstring.
    is_synthetic: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    razorpay_created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def transition_to(self, new_status: str) -> None:
        allowed = VALID_PAYMENT_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidPaymentTransition(self.status, new_status)
        self.status = new_status

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<Payment id={self.id} razorpay_payment_id={self.razorpay_payment_id} "
            f"status={self.status} amount={self.amount}>"
        )
