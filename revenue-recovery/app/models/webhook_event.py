"""
WebhookEvent: the single table Phase 1 needs.

This table is our record of every webhook we've received, whether we
successfully processed it, ignored it as a duplicate, or rejected it.
It serves two purposes:

  1. Idempotency: before processing an event, we check whether its
     `event_id` (Razorpay's `x-razorpay-event-id` header value) already
     exists in this table. If it does, we've seen it before and skip
     reprocessing.

  2. Audit trail: we keep the raw payload (as JSON) so that if we need to
     debug "what exactly did Razorpay send us for payment X", we can look
     it up without needing Razorpay's dashboard.

We deliberately do NOT create `Payment`, `Customer`, `Order`, or
`RecoveryAction` tables yet. Those belong to later phases, once we're
actually doing something with the events beyond storing them. Adding
them now would mean guessing at a schema we don't have real requirements
for yet.
"""

from datetime import datetime, timezone

from sqlalchemy import JSON, DateTime, Index, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class WebhookEvent(Base):
    """
    A single received webhook event, from any provider.

    `provider` is included (rather than assuming everything is Razorpay)
    because in a later phase we may add other providers (e.g. Stripe for
    international payments). It costs nothing now and avoids a painful
    migration later -- this is a case where a small amount of forward
    thinking in the *schema* is cheap, unlike forward-implementing whole
    subsystems.
    """

    __tablename__ = "webhook_events"
    __table_args__ = (
        # This is what actually enforces idempotency at the database
        # level: even if two requests for the same event somehow race
        # past an application-level check, the database will reject the
        # second insert.
        UniqueConstraint("provider", "event_id", name="uq_provider_event_id"),
        Index("ix_webhook_events_event_type", "event_type"),
    )

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    provider: Mapped[str] = mapped_column(String(32), nullable=False, default="razorpay")

    # Razorpay's x-razorpay-event-id header value. Unique per event,
    # per Razorpay's webhook documentation.
    event_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)

    # e.g. "payment.captured", "payment.failed"
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # The full, raw JSON payload Razorpay sent us, for audit/debugging.
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)

    # Lifecycle timestamps.
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=_utcnow
    )
    processed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # "received" -> "processed" | "ignored_duplicate" | "failed"
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="received")

    def __repr__(self) -> str:  # pragma: no cover - debugging aid only
        return (
            f"<WebhookEvent id={self.id} provider={self.provider} "
            f"event_id={self.event_id} event_type={self.event_type} "
            f"status={self.status}>"
        )
