"""
RecoveryAction: a single scheduled/executed action within a recovery case.

For Phase 2, RETRY_PAYMENT is the only action type actually executed
(via Celery, see app/tasks/recovery_tasks.py). Other action types are
represented in the schema so the model doesn't need another migration
when they're implemented, but nothing in Phase 2 schedules or executes
them.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base

ACTION_TYPES = {
    "RETRY_PAYMENT",
    "REQUEST_PAYMENT_METHOD_UPDATE",
    "SEND_PAYMENT_LINK",
    "MANUAL_REVIEW",
}

# PENDING    -> scheduled, not yet due/executed
# PROCESSING -> the worker has picked it up and is executing it
# SUCCESS    -> the action achieved its goal (e.g. retry payment succeeded)
# FAILED     -> the action did not achieve its goal
# CANCELLED  -> superseded (e.g. the case was resolved through another
#               path -- a webhook for an earlier attempt on the same
#               order -- while this action was PENDING or still
#               PROCESSING; see recovery_service.on_payment_captured_via_retry
#               and app/tasks/recovery_tasks.py's post-gateway-call
#               status re-check for where this transition originates)
VALID_RECOVERY_ACTION_TRANSITIONS: dict[str, set[str]] = {
    "PENDING": {"PROCESSING", "CANCELLED"},
    "PROCESSING": {"SUCCESS", "FAILED", "CANCELLED"},
    "SUCCESS": set(),
    "FAILED": set(),
    "CANCELLED": set(),
}


class InvalidRecoveryActionTransition(Exception):
    def __init__(self, current: str, attempted: str):
        self.current = current
        self.attempted = attempted
        super().__init__(f"Cannot transition recovery action from {current} to {attempted}")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class RecoveryAction(Base):
    __tablename__ = "recovery_actions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    recovery_case_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False, index=True
    )

    action_type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="PENDING")
    attempt_number: Mapped[int] = mapped_column(Integer, nullable=False)

    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    executed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Short human-readable outcome, e.g. "retry payment captured" or
    # "gateway declined: insufficient funds". Not the full gateway
    # response -- that level of detail isn't needed here and duplicating
    # it would just be another raw-payload dump.
    result: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def transition_to(self, new_status: str) -> None:
        allowed = VALID_RECOVERY_ACTION_TRANSITIONS.get(self.status, set())
        if new_status not in allowed:
            raise InvalidRecoveryActionTransition(self.status, new_status)
        self.status = new_status

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<RecoveryAction id={self.id} recovery_case_id={self.recovery_case_id} "
            f"action_type={self.action_type} status={self.status}>"
        )