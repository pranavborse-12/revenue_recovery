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


class CustomerSummaryOut(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    customer_id: str | None = None
    previous_recovery_history: str | None = None


class PaymentSummaryOut(BaseModel):
    payment_id: str
    order_id: str | None = None
    amount: int
    currency: str
    status: str
    failure_category: str | None = None
    failure_reason: str | None = None
    failure_code: str | None = None
    created_at: datetime | None = None


class RecoveryDecisionOut(BaseModel):
    recommended_action: str | None = None
    current_strategy: str | None = None
    attempt_number: int | None = None
    accepted: bool | None = None
    executed: bool | None = None
    actual_action_executed: str | None = None
    status: str | None = None
    confidence: float | None = None


class AIInsightOut(BaseModel):
    model: str | None = None
    recommended_action: str | None = None
    recommendation: str | None = None
    confidence: float | None = None
    reason: str | None = None
    supporting_evidence: str | None = None
    decision_timestamp: datetime | None = None


class HistoricalEvidenceOut(BaseModel):
    similar_cases: int | None = None
    successful_recoveries: int | None = None
    historical_recovery_rate: float | None = None
    best_strategy: str | None = None
    best_strategy_recovery_rate: float | None = None
    action_breakdown: dict[str, dict[str, float | int]] = {}


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
    customer_email: str | None = None
    customer_name: str | None = None
    recovery_probability: float | None = None
    ai_recommendation: str | None = None
    ai_confidence: float | None = None


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
    customer: CustomerSummaryOut = CustomerSummaryOut()
    payment: PaymentSummaryOut | None = None
    decision: RecoveryDecisionOut = RecoveryDecisionOut()
    ai_insight: AIInsightOut = AIInsightOut()
    historical_evidence: HistoricalEvidenceOut = HistoricalEvidenceOut()


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