"""
RecoveryCase: tracks the recovery workflow for one failed payment.

One recovery case per payment that has failed and is eligible for
recovery. A partial unique index (see the migration) enforces that a
payment can have at most one NON-terminal recovery case at a time --
this is the DB-level guardrail against duplicate webhook delivery
creating two competing recovery tracks for the same failure.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

# OPEN         -> just created, no strategy/action yet
# IN_PROGRESS  -> a recovery action has been scheduled/executed at least once
# RECOVERED    -> the payment eventually succeeded (terminal)
# EXHAUSTED    -> max attempts reached without success (terminal)
# CANCELLED    -> manually cancelled (terminal)
VALID_RECOVERY_CASE_TRANSITIONS: dict[str, set[str]] = {
    "OPEN": {"IN_PROGRESS", "CANCELLED"},
    "IN_PROGRESS": {"RECOVERED", "EXHAUSTED", "IN_PROGRESS", "CANCELLED"},
    "RECOVERED": set(),
    "EXHAUSTED": set(),
    "CANCELLED": set(),
}

TERMINAL_RECOVERY_CASE_STATUSES = {"RECOVERED", "EXHAUSTED", "CANCELLED"}


class InvalidRecoveryCaseTransition(Exception):
    def __init__(self, current: str, attempted: str):
        self.current = current
        self.attempted = attempted
        super().__init__(f"Cannot transition recovery case from {current} to {attempted}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    __table_args__ = (
        Index("ix_recovery_cases_status", "status"),
        Index("ix_recovery_cases_payment_id", "payment_id"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    payment_id: Mapped[int] = mapped_column(
        ForeignKey("payments.id", ondelete="CASCADE"), nullable=False
    )

    failure_category: Mapped[str] = mapped_column(String(32), nullable=False)
    amount: Mapped[int] = mapped_column(Integer, nullable=False)

    status: Mapped[str] = mapped_column(String(16), nullable=False, default="OPEN")

    # The strategy currently selected for this case, e.g. "RETRY_PAYMENT".
    # Nullable because a freshly-OPENed case may not have one chosen yet.
    current_strategy: Mapped[str | None] = mapped_column(String(32), nullable=True)

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow, onupdate=_utcnow
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def transition_to(self, new_status: str) -> None:
        allowed = VALID_RECOVERY_CASE_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidRecoveryCaseTransition(self.status, new_status)
        self.status = new_status
        if new_status in TERMINAL_RECOVERY_CASE_STATUSES:
            self.resolved_at = _utcnow()

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RecoveryCase id={self.id} payment_id={self.payment_id} "
            f"status={self.status} attempt_count={self.attempt_count}>"
        )
