"""Response schemas for the recovery API. Phase 3 additions at the bottom."""

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


# --- Phase 3 additions ---

class PaymentLinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    razorpay_short_url: str
    status: str
    amount: int
    currency: str
    created_at: datetime
    expires_at: datetime | None


class RecoveryCommunicationOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    channel: str
    type: str
    status: str
    sent_at: datetime | None
    created_at: datetime


class CustomerRecoveryTriggerResponse(BaseModel):
    recovery_case_id: int
    status: str
    detail: str


class BatchResultOut(BaseModel):
    cases_processed: int
    revenue_at_risk: int
    recovered_revenue: int
    revenue_recovery_rate: float
    recovered_cases: int
    escalated_cases: int
    stopped_cases: int
    retries_executed: int
    payment_links_created: int
    emails_sent: int
    ai_decisions: int
    ai_decisions_executed: int
    ai_policy_rejections: int
    currency_note: str = "Amounts are in the smallest currency unit (e.g. paise for INR)."


class RecoveryCaseDetailOut(RecoveryCaseOut):
    actions: list[RecoveryActionOut]
    razorpay_payment_id: str
    razorpay_order_id: str | None
    currency: str
    payment_link: PaymentLinkOut | None = None
    communications: list[RecoveryCommunicationOut] = []


class RecoveryStatsOut(BaseModel):
    total_failed_payments: int
    total_revenue_at_risk: int
    total_recovered_revenue: int
    active_recovery_cases: int
    recovered_cases: int
    exhausted_cases: int
    awaiting_customer_cases: int
    recovery_rate: float
    currency_note: str = "Amounts are in the smallest currency unit (e.g. paise for INR)."


class RetryNowResponse(BaseModel):
    recovery_case_id: int
    status: str
    detail: str