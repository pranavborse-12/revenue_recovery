"""add executed/outcome columns to ai_recovery_decisions (live agent)

Revision ID: 0006_ai_agent_execution
Revises: 0005_ai_recovery_decisions
Create Date: 2026-08-30
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_ai_agent_execution"
down_revision = "0005_ai_recovery_decisions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_recovery_decisions",
        sa.Column("executed", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("ai_recovery_decisions", sa.Column("outcome", sa.String(512), nullable=True))


def downgrade() -> None:
    op.drop_column("ai_recovery_decisions", "outcome")
    op.drop_column("ai_recovery_decisions", "executed")