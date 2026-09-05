"""widen recovery_cases.status to fit AWAITING_CUSTOMER

Revision ID: 0004_widen_recovery_case_status
Revises: 0003_phase3_customer_recovery
Create Date: 2026-08-29

Bug: recovery_cases.status was created as VARCHAR(16) in 95f7c2bb04cb,
sized for Phase 2's longest value at the time (IN_PROGRESS, 11 chars).
AWAITING_CUSTOMER is 18 chars -- Postgres rejects the write with
StringDataRightTruncation at commit time, after all the in-memory Phase
3 work (payment link creation, etc.) already happened, then the whole
transaction rolls back. This migration only widens the column; no data
is touched, no other column/table is affected.
"""
from alembic import op
import sqlalchemy as sa

revision = "0004_widen_recovery_case_status"
down_revision = "0003_phase3_customer_recovery"
branch_labels = None
depends_on = None

OLD_LENGTH = 16
NEW_LENGTH = 32  # generous headroom for any future status without needing another migration


def upgrade() -> None:
    op.alter_column(
        "recovery_cases",
        "status",
        existing_type=sa.String(length=OLD_LENGTH),
        type_=sa.String(length=NEW_LENGTH),
        existing_nullable=False,
    )


def downgrade() -> None:
    # Reversible only if no row currently holds a value longer than 16
    # chars (i.e. AWAITING_CUSTOMER rows would need to be dealt with
    # first) -- Alembic will raise if Postgres can't truncate safely.
    op.alter_column(
        "recovery_cases",
        "status",
        existing_type=sa.String(length=NEW_LENGTH),
        type_=sa.String(length=OLD_LENGTH),
        existing_nullable=False,
    )