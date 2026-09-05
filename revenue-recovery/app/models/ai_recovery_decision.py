"""
AIRecoveryDecision: audit record of one AI recommendation.

Started audit-only (nothing read this table). Now also used to gate live
agent execution: `executed` counts as the agent's action budget (see
recovery_agent.py), independent of and never conflated with
RetryPolicy.max_attempts / RecoveryCase.attempt_count -- every live
intervention is implemented by reusing the exact function the
deterministic path already calls, so the two counters can't diverge.

Multi-agent addition: one row per participating agent (agent_role=
"strategist"|"historical_analyst"|"critic") PLUS one row for the
reconciled result (agent_role="final") per decision point. Only the
"final" row can have executed=True -- individual agent opinions are
never executed directly (see recovery_agent.get_multi_agent_recommendation).
agent_has_budget() already filters on executed=True, so per-agent rows
never affect the budget count.
"""

from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AIRecoveryDecision(Base):
    __tablename__ = "ai_recovery_decisions"
    __table_args__ = (Index("ix_ai_recovery_decisions_recovery_case_id", "recovery_case_id"),)

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    organization_id: Mapped[int | None] = mapped_column(
        ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=True, index=True
    )

    recovery_case_id: Mapped[int] = mapped_column(
        ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False
    )
    recovery_action_id: Mapped[int | None] = mapped_column(
        ForeignKey("recovery_actions.id", ondelete="SET NULL"), nullable=True
    )

    recommended_action: Mapped[str] = mapped_column(String(32), nullable=False)
    recommended_delay_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    confidence: Mapped[float] = mapped_column(Float, nullable=False)
    reason: Mapped[str] = mapped_column(String(512), nullable=False)
    model: Mapped[str] = mapped_column(String(64), nullable=False)

    # "strategist" | "historical_analyst" | "critic" | "final". Default
    # "final" so any pre-multi-agent rows read sensibly without a backfill.
    agent_role: Mapped[str] = mapped_column(String(24), nullable=False, default="final")
    # "mistral" | "groq" | None (None for a "final" row -- a
    # reconciliation of the three above it, not its own provider call).
    provider: Mapped[str | None] = mapped_column(String(24), nullable=True)

    accepted: Mapped[bool] = mapped_column(Boolean, nullable=False)
    rejection_reason: Mapped[str | None] = mapped_column(String(256), nullable=True)

    # Was a tool actually invoked for this decision? Only ever True on a
    # "final" row -- individual agent opinions are never executed
    # directly. True whether the tool call succeeded or failed -- an
    # attempted-but-failed tool call still consumes one unit of the
    # agent's budget (see recovery_agent.agent_has_budget), it just also
    # falls through to the deterministic default for that round.
    executed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    outcome: Mapped[str | None] = mapped_column(String(512), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"<AIRecoveryDecision id={self.id} recovery_case_id={self.recovery_case_id} "
            f"role={self.agent_role} action={self.recommended_action} executed={self.executed}>"
        )
