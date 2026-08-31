"""
Strict schema for AI recovery recommendations.

Only actions this backend can actually execute today are allowed --
SEND_PAYMENT_LINK maps to the existing AWAITING_CUSTOMER/Phase 3 path
(link + email together; there's no standalone "send email only" action
in this codebase, so it's deliberately not in this enum). Anything the
model returns outside this schema is rejected before it's ever used --
see ai_recovery_service.py, which never returns an unvalidated object.
"""

from pydantic import BaseModel, Field, field_validator

SUPPORTED_AI_ACTIONS = {"RETRY_PAYMENT", "SEND_PAYMENT_LINK", "MANUAL_REVIEW", "WAIT"}

MIN_DELAY_MINUTES = 1
MAX_DELAY_MINUTES = 10080  # 1 week -- a sanity ceiling, not the real retry policy


class AIRecommendation(BaseModel):
    action: str
    delay_minutes: int | None = None
    confidence: float
    reason: str = Field(max_length=512)

    @field_validator("action")
    @classmethod
    def action_must_be_supported(cls, v: str) -> str:
        if v not in SUPPORTED_AI_ACTIONS:
            raise ValueError(f"action '{v}' is not one of {sorted(SUPPORTED_AI_ACTIONS)}")
        return v

    @field_validator("confidence")
    @classmethod
    def confidence_in_bounds(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            raise ValueError("confidence must be between 0.0 and 1.0")
        return v

    @field_validator("delay_minutes")
    @classmethod
    def delay_in_bounds(cls, v: int | None) -> int | None:
        if v is not None and not (MIN_DELAY_MINUTES <= v <= MAX_DELAY_MINUTES):
            raise ValueError(f"delay_minutes must be between {MIN_DELAY_MINUTES} and {MAX_DELAY_MINUTES}")
        return v