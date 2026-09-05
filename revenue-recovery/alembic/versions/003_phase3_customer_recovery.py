"""add phase 3 payment_links and recovery_communications tables

Revision ID: 0003_phase3_customer_recovery
Revises: ce34b5219ac1
Create Date: 2026-08-29

Chain: 120e07d931a3 (webhook_events) -> 95f7c2bb04cb (payment recovery
tables) -> ce34b5219ac1 (failure_reason on payments, current head) ->
this migration. recovery_cases.status is already a plain String(16)
column with no CHECK constraint, so no column-type migration is needed
for the new AWAITING_CUSTOMER value -- only new tables are added here.
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_phase3_customer_recovery"
down_revision = "ce34b5219ac1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "payment_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recovery_case_id", sa.Integer(),
                  sa.ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("razorpay_payment_link_id", sa.String(64), nullable=False),
        sa.Column("razorpay_short_url", sa.String(512), nullable=False),
        sa.Column("amount", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(8), nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="CREATED"),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index("ix_payment_links_recovery_case_id", "payment_links", ["recovery_case_id"])
    op.create_unique_constraint(
        "uq_payment_links_razorpay_payment_link_id", "payment_links", ["razorpay_payment_link_id"]
    )
    # DB-level backstop for customer_recovery_service.create_payment_link's
    # pre-check: only one ACTIVE (status='CREATED') link per case.
    op.create_index(
        "uq_payment_links_active_per_case",
        "payment_links",
        ["recovery_case_id"],
        unique=True,
        postgresql_where=sa.text("status = 'CREATED'"),
        sqlite_where=sa.text("status = 'CREATED'"),
    )

    op.create_table(
        "recovery_communications",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("recovery_case_id", sa.Integer(),
                  sa.ForeignKey("recovery_cases.id", ondelete="CASCADE"), nullable=False),
        sa.Column("channel", sa.String(16), nullable=False, server_default="EMAIL"),
        sa.Column("type", sa.String(32), nullable=False, server_default="PAYMENT_LINK"),
        sa.Column("status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("provider_message_id", sa.String(255), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
    )
    op.create_index(
        "ix_recovery_communications_recovery_case_id", "recovery_communications", ["recovery_case_id"]
    )
    # DB-level backstop against duplicate customer emails: only one
    # ACTIVE (PENDING/SENT) communication of a given type per case.
    op.create_index(
        "uq_recovery_communications_active_per_case_type",
        "recovery_communications",
        ["recovery_case_id", "type"],
        unique=True,
        postgresql_where=sa.text("status IN ('PENDING', 'SENT')"),
        sqlite_where=sa.text("status IN ('PENDING', 'SENT')"),
    )


def downgrade() -> None:
    op.drop_index("uq_recovery_communications_active_per_case_type", table_name="recovery_communications")
    op.drop_index("ix_recovery_communications_recovery_case_id", table_name="recovery_communications")
    op.drop_table("recovery_communications")

    op.drop_index("uq_payment_links_active_per_case", table_name="payment_links")
    op.drop_constraint("uq_payment_links_razorpay_payment_link_id", "payment_links", type_="unique")
    op.drop_index("ix_payment_links_recovery_case_id", table_name="payment_links")
    op.drop_table("payment_links")