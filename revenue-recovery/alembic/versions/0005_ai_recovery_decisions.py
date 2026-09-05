"""add ai_recovery_decisions table (Phase 4, audit-only)

Revision ID: 0005_ai_recovery_decisions
Revises: 0004_widen_recovery_case_status
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_ai_recovery_decisions"
down_revision = "0004_widen_recovery_case_status"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_recovery_decisions",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recovery_case_id", sa.Integer(),
                  sa.ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("recovery_action_id", sa.Integer(),
                  sa.ForeignKey("recovery_actions.id", ondelete="SET NULL"), nullable=True),
        sa.Column("recommended_action", sa.String(32), nullable=False),
        sa.Column("recommended_delay_minutes", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("reason", sa.String(512), nullable=False),
        sa.Column("model", sa.String(64), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False),
        sa.Column("rejection_reason", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_ai_recovery_decisions_recovery_case_id", "ai_recovery_decisions", ["recovery_case_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_ai_recovery_decisions_recovery_case_id", table_name="ai_recovery_decisions")
    op.drop_table("ai_recovery_decisions")