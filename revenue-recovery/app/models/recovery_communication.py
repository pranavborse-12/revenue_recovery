"""
RecoveryCommunication: was the customer already contacted for this
recovery case + this message type? A partial unique index (see the
migration) on (recovery_case_id, type) WHERE status IN ('PENDING',
'SENT') is what actually prevents a Celery retry or duplicate API call
from sending the same email twice -- the same pattern WebhookEvent and
RecoveryCase use for their own idempotency.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

CHANNELS = {"EMAIL"}
TYPES = {"PAYMENT_LINK"}
STATUSES = {"PENDING", "SENT", "FAILED"}

# PENDING/SENT block a duplicate send; FAILED does not (so a retry can
# proceed) -- see the migration's partial unique index.
ACTIVE_COMMUNICATION_STATUSES = {"PENDING", "SENT"}


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecoveryCommunication(Base):
    __tablename__ = "recovery_communications"
    __table_args__ = (Index("ix_recovery_communications_recovery_case_id", "recovery_case_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    recovery_case_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False
    )

    channel: Mapped[str] = mapped_column(String(16), nullable=False, default="EMAIL")
    type: Mapped[str] = mapped_column(String(32), nullable=False, default="PAYMENT_LINK")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")

    # Diagnostic only -- NOT used for idempotency (status is).
    provider_message_id: Mapped[str | None] = mapped_column(String(255), nullable=True)

    sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RecoveryCommunication id={self.id} recovery_case_id={self.recovery_case_id} "
            f"type={self.type} status={self.status}>"
        )