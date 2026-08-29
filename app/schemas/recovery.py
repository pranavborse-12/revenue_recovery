"""Response schemas for the recovery API (app/api/routes/recovery.py)."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict


class RecoveryActionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    action_type: str
    status: str
    attempt_number: int
    scheduled_at: datetime
    executed_at: datetime | None
    result: str | None


class RecoveryCaseOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    payment_id: int
    failure_category: str
    amount: int
    status: str
    current_strategy: str | None
    attempt_count: int
    created_at: datetime
    updated_at: datetime
    resolved_at: datetime | None


class RecoveryCaseDetailOut(RecoveryCaseOut):
    actions: list[RecoveryActionOut]
    razorpay_payment_id: str
    razorpay_order_id: str | None
    currency: str


class RecoveryStatsOut(BaseModel):
    total_failed_payments: int
    total_revenue_at_risk: int
    total_recovered_revenue: int
    active_recovery_cases: int
    recovered_cases: int
    exhausted_cases: int
    recovery_rate: float  # recovered / (recovered + exhausted), 0.0 if no resolved cases yet
    currency_note: str = "Amounts are in the smallest currency unit (e.g. paise for INR)."


class RetryNowResponse(BaseModel):
    recovery_case_id: int
    status: str
    detail: str
