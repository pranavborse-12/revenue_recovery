"""
PaymentLink: a Razorpay Payment Link generated for customer-assisted
recovery (Phase 3) -- distinct from the fire-and-forget link Phase 2's
RazorpayPaymentGateway.retry_payment() creates (that one's URL is never
stored). This one is a tracked resource so we can (a) prevent creating a
duplicate link for the same case and (b) know what URL to put in the
recovery email.

Only one ACTIVE (status=CREATED) link per recovery case -- enforced here
at the application level (customer_recovery_service) and backstopped by
a partial unique index (see the migration), same pattern as
RecoveryCase's own partial unique index against a payment.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# CREATED   -> generated, awaiting customer payment
# PAID      -> resolved via payment.captured (recovery_service marks this)
# EXPIRED   -> link's expiry passed unpaid (not auto-detected in Phase 3)
# CANCELLED -> superseded (e.g. the recovery case itself was cancelled)
VALID_PAYMENT_LINK_TRANSITIONS: dict[str, set[str]] = {
    "CREATED": {"PAID", "EXPIRED", "CANCELLED"},
    "PAID": set(),
    "EXPIRED": set(),
    "CANCELLED": set(),
}

ACTIVE_PAYMENT_LINK_STATUSES = {"CREATED"}


class InvalidPaymentLinkTransition(Exception):
    def __init__(self, current: str, attempted: str):
        self.current = current
        self.attempted = attempted
        super().__init__(f"Cannot transition payment link from {current} to {attempted}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class PaymentLink(Base):
    __tablename__ = "payment_links"
    __table_args__ = (Index("ix_payment_links_recovery_case_id", "recovery_case_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    recovery_case_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False
    )

    # Razorpay's own link id, e.g. "plink_XXXX" -- our real dedup key
    # against Razorpay itself.
    razorpay_payment_link_id: Mapped[str] = mapped_column(
        String(64), nullable=False, unique=True, index=True
    )
    razorpay_short_url: Mapped[str] = mapped_column(String(512), nullable=False)

    amount: Mapped[int] = mapped_column(Integer, nullable=False)
    currency: Mapped[str] = mapped_column(String(8), nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="CREATED")

    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )

    def transition_to(self, new_status: str) -> None:
        allowed = VALID_PAYMENT_LINK_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidPaymentLinkTransition(self.status, new_status)
        self.status = new_status

    def __repr__(self) -> str:  # pragma: no cover
        return f"<PaymentLink id={self.id} recovery_case_id={self.recovery_case_id} status={self.status}>"