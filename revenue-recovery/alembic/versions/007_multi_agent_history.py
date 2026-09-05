"""add is_synthetic to payments, agent_role/provider to ai_recovery_decisions

Revision ID: 0007_multi_agent_history
Revises: 0006_ai_agent_execution
Create Date: 2026-08-31
"""
from alembic import op
import sqlalchemy as sa

revision = "0007_multi_agent_history"
down_revision = "0006_ai_agent_execution"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "payments",
        sa.Column("is_synthetic", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column(
        "ai_recovery_decisions",
        sa.Column("agent_role", sa.String(24), nullable=False, server_default="final"),
    )
    op.add_column("ai_recovery_decisions", sa.Column("provider", sa.String(24), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_recovery_decisions", "provider")
    op.drop_column("ai_recovery_decisions", "agent_role")
    op.drop_column("payments", "is_synthetic")