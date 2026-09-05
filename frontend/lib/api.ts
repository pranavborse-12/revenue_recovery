import { auth } from '@/lib/firebase';

export type RecoveryStatus = 'OPEN' | 'IN_PROGRESS' | 'AWAITING_CUSTOMER' | 'RECOVERED' | 'EXHAUSTED' | 'CANCELLED';
export type ActionStatus = 'PENDING' | 'PROCESSING' | 'SUCCESS' | 'FAILED' | 'CANCELLED';
export type PaymentLinkStatus = 'CREATED' | 'PAID' | 'EXPIRED' | 'CANCELLED';
export type FailureCategory = 'INSUFFICIENT_FUNDS' | 'TEMPORARY_NETWORK_ERROR' | 'PAYMENT_METHOD_INVALID' | 'PAYMENT_METHOD_EXPIRED' | 'BANK_DECLINED' | 'UNKNOWN';
export type ActionType = 'RETRY_PAYMENT' | 'REQUEST_PAYMENT_METHOD_UPDATE' | 'SEND_PAYMENT_LINK' | 'MANUAL_REVIEW';

export interface RecoveryStats {
  total_failed_payments: number;
  total_revenue_at_risk: number;
  total_recovered_revenue: number;
  active_recovery_cases: number;
  recovered_cases: number;
  exhausted_cases: number;
  awaiting_customer_cases: number;
  recovery_rate: number;
  currency_note: string;
}

export interface CustomerSummary {
  name: string | null;
  email: string | null;
  phone: string | null;
  customer_id: string | null;
  previous_recovery_history: string | null;
}

export interface PaymentSummary {
  payment_id: string;
  order_id: string | null;
  amount: number;
  currency: string;
  status: string;
  failure_category: string | null;
  failure_reason: string | null;
  failure_code: string | null;
  created_at: string | null;
}

export interface RecoveryDecision {
  recommended_action: string | null;
  current_strategy: string | null;
  attempt_number: number | null;
  accepted: boolean | null;
  executed: boolean | null;
  actual_action_executed: string | null;
  status: string | null;
  confidence: number | null;
}

export interface AIInsight {
  model: string | null;
  recommended_action: string | null;
  recommendation: string | null;
  confidence: number | null;
  reason: string | null;
  supporting_evidence: string | null;
  decision_timestamp: string | null;
}

export interface HistoricalEvidence {
  similar_cases: number | null;
  successful_recoveries: number | null;
  historical_recovery_rate: number | null;
  best_strategy: string | null;
  best_strategy_recovery_rate: number | null;
  action_breakdown: Record<string, Record<string, number>>;
}

export interface RecoveryAction {
  id: number;
  action_type: ActionType;
  status: ActionStatus;
  attempt_number: number;
  scheduled_at: string;
  executed_at: string | null;
  result: string | null;
}

export interface PaymentLink {
  id: number;
  razorpay_short_url: string;
  status: PaymentLinkStatus;
  amount: number;
  currency: string;
  created_at: string;
  expires_at: string | null;
}

export interface Communication {
  id: number;
  channel: 'EMAIL' | 'SMS';
  type: 'PAYMENT_LINK' | 'RECOVERY_NOTICE';
  status: 'SENT' | 'FAILED';
  sent_at: string;
  created_at: string;
}

export interface RecoveryCase {
  id: number;
  payment_id: number;
  failure_category: FailureCategory;
  amount: number;
  status: RecoveryStatus;
  current_strategy: string;
  attempt_count: number;
  created_at: string;
  updated_at: string;
  resolved_at: string | null;
  customer_email?: string | null;
  customer_name?: string | null;
  recovery_probability?: number | null;
  ai_recommendation?: string | null;
  ai_confidence?: number | null;
}

export interface RecoveryCaseDetail extends RecoveryCase {
  actions: RecoveryAction[];
  razorpay_payment_id: string;
  razorpay_order_id: string;
  currency: string;
  payment_link: PaymentLink | null;
  communications: Communication[];
  customer: CustomerSummary;
  payment: PaymentSummary | null;
  decision: RecoveryDecision;
  ai_insight: AIInsight;
  historical_evidence: HistoricalEvidence;
}

export interface BatchAnalytics {
  cases_processed: number;
  revenue_at_risk: number;
  recovered_revenue: number;
  recovery_rate: number;
  recovered_cases: number;
  escalated_cases: number;
  stopped_cases: number;
  retries_executed: number;
  payment_links_created: number;
  emails_sent: number;
  ai_decisions: number;
  ai_decisions_executed: number;
  ai_policy_rejections: number;
}

const BASE_URL = '/api';

async function fetchApi<T>(path: string, options?: RequestInit): Promise<T> {
  const currentUser = auth?.currentUser;
  let token = currentUser ? await currentUser.getIdToken() : undefined;

  const request = () => fetch(`${BASE_URL}${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...options?.headers,
    },
  });

  let response = await request();
  if (response.status === 401 && currentUser) {
    token = await currentUser.getIdToken(true);
    response = await request();
  }

  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: 'An unexpected error occurred' }));
    throw new Error(error.detail || `Error: ${response.status}`);
  }

  return response.json();
}

export const api = {
  getStats: () => fetchApi<RecoveryStats>('/recovery/stats'),
  getCases: (statusFilter?: string, limit = 50) => {
    const params = new URLSearchParams();
    if (statusFilter) params.append('status_filter', statusFilter);
    params.append('limit', limit.toString());
    return fetchApi<RecoveryCase[]>(`/recovery/cases?${params.toString()}`);
  },
  getCaseDetail: (id: number) => fetchApi<RecoveryCaseDetail>(`/recovery/cases/${id}`),
  retryCase: (id: number) => fetchApi<{ recovery_case_id: number; status: string; detail: string }>(`/recovery/cases/${id}/retry`, { method: 'POST' }),
  recoverNow: (id: number) => fetchApi<{ recovery_case_id: number; status: string; detail: string }>(`/recovery/cases/${id}/recover-now`, { method: 'POST' }),
  getBatchAnalytics: () => fetchApi<BatchAnalytics>('/recovery/batch'),
};
