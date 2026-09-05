'use client';

import * as React from 'react';
import { useParams, useRouter } from 'next/navigation';
import { api, type RecoveryCaseDetail } from '@/lib/api';
import { formatCurrency, formatDate, formatProbability, cn } from '@/lib/utils';
import { Button } from '@/components/ui/Button';
import { Badge } from '@/components/ui/Badge';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import {
  ArrowLeft,
  RefreshCcw,
  Zap,
  Link as LinkIcon,
  Mail,
  Clock,
  CheckCircle2,
  AlertCircle,
  History,
  ShieldCheck,
  CreditCard,
  ChevronRight,
  ExternalLink,
  Users
} from 'lucide-react';

export default function CaseDetailPage() {
  const params = useParams();
  const router = useRouter();
  const caseId = parseInt(params.id as string);

  const [caseData, setCaseData] = React.useState<RecoveryCaseDetail | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [isActionLoading, setIsActionLoading] = React.useState(false);
  const [error, setError] = React.useState<string | null>(null);
  const [actionError, setActionError] = React.useState<string | null>(null);

  const fetchDetail = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await api.getCaseDetail(caseId);
      setCaseData(data);
      setError(null);
    } catch (err) {
      console.error(err);
      setError('Failed to load case details.');
    } finally {
      setIsLoading(false);
    }
  }, [caseId]);

  React.useEffect(() => {
    const timer = setTimeout(() => fetchDetail(), 0);
    return () => clearTimeout(timer);
  }, [fetchDetail]);

  const handleRetry = async () => {
    setActionError(null);
    setIsActionLoading(true);
    try {
      await api.retryCase(caseId);
      await fetchDetail();
    } catch {
      setActionError('Retry could not be started. Please try again.');
    } finally {
      setIsActionLoading(false);
    }
  };

  const handleRecoverNow = async () => {
    setActionError(null);
    setIsActionLoading(true);
    try {
      await api.recoverNow(caseId);
      await fetchDetail();
    } catch {
      setActionError('Customer recovery could not be started. Please try again.');
    } finally {
      setIsActionLoading(false);
    }
  };

  if (isLoading && !caseData) {
    return <div className="animate-pulse space-y-8">
      <div className="h-8 w-48 bg-slate-200 rounded" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        <div className="lg:col-span-2 space-y-8">
          <div className="h-64 bg-slate-100 rounded-xl" />
          <div className="h-64 bg-slate-100 rounded-xl" />
        </div>
        <div className="h-96 bg-slate-100 rounded-xl" />
      </div>
    </div>;
  }

  if (!caseData) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
        <p className="text-sm text-slate-500">{error || 'Case details are unavailable.'}</p>
        <Button variant="outline" onClick={fetchDetail}>Try again</Button>
      </div>
    );
  }

  return (
    <div className="space-y-8 pb-20">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-6">
        <div className="flex items-center gap-4">
          <Button variant="ghost" size="sm" onClick={() => router.back()} className="p-2 h-10 w-10">
            <ArrowLeft className="w-5 h-5" />
          </Button>
          <div className="space-y-1">
            <div className="flex items-center gap-3">
              <h1 className="text-3xl font-bold tracking-tight">CASE-{caseData.id.toString().padStart(4, '0')}</h1>
              <Badge variant={
                caseData.status === 'RECOVERED' ? 'success' :
                caseData.status === 'EXHAUSTED' ? 'error' :
                caseData.status === 'AWAITING_CUSTOMER' ? 'warning' : 'info'
              }>
                {caseData.status.replace(/_/g, ' ')}
              </Badge>
            </div>
            <p className="text-slate-500 font-medium">{caseData.failure_category.replace(/_/g, ' ')} • {formatCurrency(caseData.amount, caseData.currency)}</p>
          </div>
        </div>
        <div className="flex items-center gap-3">
          {caseData.status === 'OPEN' || caseData.status === 'IN_PROGRESS' ? (
            <Button
              onClick={handleRetry}
              disabled={isActionLoading}
              className="gap-2"
            >
              <RefreshCcw className={cn("w-4 h-4", isActionLoading && "animate-spin")} />
              Retry Now
            </Button>
          ) : null}
          {caseData.status === 'AWAITING_CUSTOMER' ? (
            <Button
              onClick={handleRecoverNow}
              disabled={isActionLoading}
              className="gap-2"
            >
              <Users className="w-4 h-4" />
              Recover Now
            </Button>
          ) : null}
          <Button variant="outline" size="sm" onClick={() => fetchDetail()} className="p-2 h-10 w-10">
            <RefreshCcw className={cn("w-4 h-4", isLoading && "animate-spin")} />
          </Button>
        </div>
      </div>
      {actionError && <p role="alert" className="rounded-xl border border-red-100 bg-red-50 px-4 py-3 text-sm text-red-700">{actionError}</p>}

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-8">
        {/* Main Content */}
        <div className="lg:col-span-2 space-y-8">
          <Card>
            <CardHeader>
              <CardTitle>Recovery Intelligence</CardTitle>
              <CardDescription>Customer context, AI recommendation, and recovery probability.</CardDescription>
            </CardHeader>
            <CardContent className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Customer</p>
                <p className="text-sm font-bold text-slate-900">{caseData.customer?.name || 'Not available'}</p>
                <p className="text-xs text-slate-500 break-all">{caseData.customer?.email || 'Not available'}</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Failure</p>
                <p className="text-sm font-bold text-slate-900">{caseData.failure_category.replace(/_/g, ' ')}</p>
                <p className="text-xs text-slate-500">{caseData.payment?.failure_reason || 'Not available'}</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Strategy</p>
                <p className="text-sm font-bold text-slate-900">{caseData.current_strategy?.replace(/_/g, ' ') || 'Not available'}</p>
                <p className="text-xs text-slate-500">Attempt {caseData.attempt_count}</p>
              </div>
              <div className="rounded-xl border border-slate-200 bg-slate-50 p-4 space-y-2">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Recovery Probability</p>
                <p className="text-2xl font-bold text-emerald-600">{formatProbability(caseData.recovery_probability)}</p>
                <p className="text-xs text-slate-500">{caseData.ai_insight?.recommended_action || 'No recommendation yet'}</p>
              </div>
            </CardContent>
          </Card>

          {/* Timeline / Status */}
          <Card>
            <CardHeader>
              <CardTitle>Recovery Journey</CardTitle>
              <CardDescription>Visual timeline of the recovery process.</CardDescription>
            </CardHeader>
            <CardContent>
              <div className="relative space-y-8 before:absolute before:left-[17px] before:top-2 before:bottom-2 before:w-px before:bg-slate-100">
                <div className="relative flex gap-6">
                  <div className="relative z-10 w-9 h-9 rounded-full bg-red-50 border border-red-100 flex items-center justify-center">
                    <AlertCircle className="w-5 h-5 text-red-600" />
                  </div>
                  <div className="space-y-1">
                    <p className="text-sm font-bold text-slate-900">Payment Failed</p>
                    <p className="text-xs text-slate-500">{formatDate(caseData.created_at)}</p>
                    <div className="mt-2 p-3 rounded-lg bg-slate-50 border border-slate-100 space-y-1">
                      <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Reason</p>
                      <p className="text-xs font-semibold text-slate-700">{caseData.failure_category.replace(/_/g, ' ')}</p>
                    </div>
                  </div>
                </div>

                {caseData.actions.map((action, i) => (
                  <div key={action.id} className="relative flex gap-6">
                    <div className={cn(
                      "relative z-10 w-9 h-9 rounded-full border flex items-center justify-center",
                      action.status === 'SUCCESS' ? "bg-emerald-50 border-emerald-100" :
                      action.status === 'FAILED' ? "bg-red-50 border-red-100" : "bg-blue-50 border-blue-100"
                    )}>
                      {action.status === 'SUCCESS' ? <CheckCircle2 className="w-5 h-5 text-emerald-600" /> :
                       action.status === 'FAILED' ? <AlertCircle className="w-5 h-5 text-red-600" /> :
                       <Clock className="w-5 h-5 text-blue-600" />}
                    </div>
                    <div className="space-y-1">
                      <p className="text-sm font-bold text-slate-900">
                        {action.action_type.replace(/_/g, ' ')} <span className="text-slate-400 font-normal">#{action.attempt_number}</span>
                      </p>
                      <p className="text-xs text-slate-500">
                        {action.executed_at ? formatDate(action.executed_at) : `Scheduled for ${formatDate(action.scheduled_at)}`}
                      </p>
                      {action.result && (
                        <p className="text-xs font-medium text-slate-500 italic mt-1">&quot;{action.result}&quot;</p>
                      )}
                    </div>
                  </div>
                ))}

                <div className="relative flex gap-6">
                  <div className="relative z-10 w-9 h-9 rounded-full bg-violet-50 border border-violet-100 flex items-center justify-center">
                    <History className="w-5 h-5 text-violet-600" />
                  </div>
                  <div className="space-y-2">
                    <p className="text-sm font-bold text-slate-900">AI recommendation</p>
                    <div className="rounded-lg bg-violet-50 border border-violet-100 p-3 text-xs text-slate-700">
                      <p className="font-bold text-violet-700">{caseData.ai_insight?.recommended_action || 'Not available'}</p>
                      <p className="mt-2">Confidence: {caseData.ai_insight?.confidence !== null && caseData.ai_insight?.confidence !== undefined ? `${(caseData.ai_insight.confidence * 100).toFixed(0)}%` : 'Not available'}</p>
                      <p className="mt-2 italic">{caseData.ai_insight?.reason || 'No reasoning available'}</p>
                    </div>
                  </div>
                </div>

                {caseData.status === 'RECOVERED' && (
                  <div className="relative flex gap-6">
                    <div className="relative z-10 w-9 h-9 rounded-full bg-emerald-500 border border-emerald-400 flex items-center justify-center shadow-[0_0_15px_rgba(16,185,129,0.3)]">
                      <Zap className="w-5 h-5 text-white" />
                    </div>
                    <div className="space-y-1">
                      <p className="text-sm font-bold text-emerald-600">Revenue Recovered</p>
                      <p className="text-xs text-slate-500">{caseData.resolved_at ? formatDate(caseData.resolved_at) : 'Completed'}</p>
                    </div>
                  </div>
                )}
              </div>
            </CardContent>
          </Card>

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Users className="w-4 h-4 text-slate-400" />
                  Customer
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3 text-sm">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Name</p>
                    <p className="font-bold text-slate-900">{caseData.customer?.name || 'Not available'}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Email</p>
                    <p className="font-bold text-slate-900 break-all">{caseData.customer?.email || 'Not available'}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Phone</p>
                    <p className="font-bold text-slate-900">{caseData.customer?.phone || 'Not available'}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Customer ID</p>
                    <p className="font-bold text-slate-900">{caseData.customer?.customer_id || 'Not available'}</p>
                  </div>
                </div>
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <CreditCard className="w-4 h-4 text-slate-400" />
                  Payment
                </CardTitle>
              </CardHeader>
              <CardContent>
                <div className="space-y-3 text-sm">
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Payment ID</p>
                    <p className="font-bold text-slate-900 break-all">{caseData.payment?.payment_id || caseData.razorpay_payment_id || 'Not available'}</p>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Amount</p>
                      <p className="font-bold text-slate-900">{formatCurrency(caseData.amount, caseData.currency)}</p>
                    </div>
                    <div>
                      <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Currency</p>
                      <p className="font-bold text-slate-900">{caseData.currency}</p>
                    </div>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Failure reason</p>
                    <p className="font-bold text-slate-900">{caseData.payment?.failure_reason || caseData.payment?.failure_code || 'Not available'}</p>
                  </div>
                  <div>
                    <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Created</p>
                    <p className="font-bold text-slate-900">{caseData.payment?.created_at ? formatDate(caseData.payment.created_at) : formatDate(caseData.created_at)}</p>
                  </div>
                </div>
              </CardContent>
            </Card>
          </div>

          {/* Payment Link & Comms */}
          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <LinkIcon className="w-4 h-4 text-slate-400" />
                  Payment Link
                </CardTitle>
              </CardHeader>
              <CardContent>
                {caseData.payment_link ? (
                  <div className="space-y-4">
                    <div className="p-3 rounded-lg bg-slate-50 border border-slate-100 flex items-center justify-between">
                      <div className="space-y-0.5">
                        <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Status</p>
                        <Badge variant={caseData.payment_link.status === 'PAID' ? 'success' : 'info'}>
                          {caseData.payment_link.status}
                        </Badge>
                      </div>
                      <a href={caseData.payment_link.razorpay_short_url} target="_blank" rel="noopener noreferrer">
                        <Button size="sm" className="gap-2">
                          Open Link
                          <ExternalLink className="w-3 h-3" />
                        </Button>
                      </a>
                    </div>
                    <div className="grid grid-cols-2 gap-4 text-xs">
                      <div>
                        <p className="text-slate-400 font-bold uppercase tracking-widest mb-1">Created</p>
                        <p className="font-bold text-slate-900">{formatDate(caseData.payment_link.created_at)}</p>
                      </div>
                      <div>
                        <p className="text-slate-400 font-bold uppercase tracking-widest mb-1">Expires</p>
                        <p className="font-bold text-slate-900">{formatDate(caseData.payment_link.expires_at)}</p>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="py-6 text-center text-slate-400 text-sm">
                    No payment link generated yet.
                  </div>
                )}
              </CardContent>
            </Card>

            <Card>
              <CardHeader className="pb-3">
                <CardTitle className="text-base flex items-center gap-2">
                  <Mail className="w-4 h-4 text-slate-400" />
                  Communications
                </CardTitle>
              </CardHeader>
              <CardContent>
                {caseData.communications.length > 0 ? (
                  <div className="space-y-3">
                    {caseData.communications.map(comm => (
                      <div key={comm.id} className="flex items-center justify-between p-2 rounded-lg border border-slate-100 bg-slate-50/50">
                        <div className="flex items-center gap-3">
                          <Mail className="w-4 h-4 text-slate-400" />
                          <div className="space-y-0.5">
                            <p className="text-xs font-bold text-slate-900">{comm.type.replace(/_/g, ' ')}</p>
                            <p className="text-[10px] text-slate-500">{formatDate(comm.sent_at)}</p>
                          </div>
                        </div>
                        <Badge variant={comm.status === 'SENT' ? 'success' : 'error'} className="text-[10px] py-0 px-1.5 h-4">
                          {comm.status}
                        </Badge>
                      </div>
                    ))}
                  </div>
                ) : (
                  <div className="py-6 text-center text-slate-400 text-sm">
                    No communications sent yet.
                  </div>
                )}
              </CardContent>
            </Card>
          </div>
        </div>

        {/* Sidebar Info */}
        <div className="space-y-8">
          <Card>
            <CardHeader>
              <CardTitle className="text-sm">Payment Details</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-1">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Razorpay ID</p>
                <div className="flex items-center justify-between font-mono text-sm font-bold text-slate-900 bg-slate-50 p-2 rounded border border-slate-100">
                  {caseData.razorpay_payment_id}
                  <CreditCard className="w-3.5 h-3.5 text-slate-300" />
                </div>
              </div>
              <div className="space-y-1">
                <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Order ID</p>
                <p className="text-sm font-bold text-slate-900">{caseData.razorpay_order_id}</p>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-1">
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Amount</p>
                  <p className="text-sm font-bold text-slate-900">{formatCurrency(caseData.amount, caseData.currency)}</p>
                </div>
                <div className="space-y-1">
                  <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Currency</p>
                  <p className="text-sm font-bold text-slate-900">{caseData.currency}</p>
                </div>
              </div>
            </CardContent>
          </Card>

          <Card className="bg-slate-50 border-dashed border-2">
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <ShieldCheck className="w-4 h-4 text-slate-400" />
                Recovery Decision
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="p-4 rounded-xl bg-white border border-slate-200 space-y-2">
                <p className="text-xs font-bold text-slate-400 uppercase tracking-widest">Recommended</p>
                <p className="text-sm font-bold text-slate-900">{caseData.decision?.recommended_action?.replace(/_/g, ' ') || 'Not available'}</p>
              </div>
              <div className="grid grid-cols-2 gap-3 text-xs">
                <div>
                  <p className="text-slate-400 font-bold uppercase tracking-widest">Confidence</p>
                  <p className="font-bold text-slate-900">{caseData.decision?.confidence !== null && caseData.decision?.confidence !== undefined ? `${(caseData.decision.confidence * 100).toFixed(0)}%` : 'Not available'}</p>
                </div>
                <div>
                  <p className="text-slate-400 font-bold uppercase tracking-widest">Accepted</p>
                  <p className="font-bold text-slate-900">{caseData.decision?.accepted === null || caseData.decision?.accepted === undefined ? 'Not available' : caseData.decision.accepted ? 'Yes' : 'No'}</p>
                </div>
              </div>
              <div className="p-3 rounded-lg bg-white border border-slate-200 text-xs text-slate-600">
                <p className="font-bold uppercase tracking-widest text-slate-400 mb-1">Actual execution</p>
                <p>{caseData.decision?.actual_action_executed || 'No execution recorded'}</p>
              </div>
              <p className="text-xs text-slate-500 leading-relaxed italic">
                {caseData.status === 'AWAITING_CUSTOMER' ? 'Awaiting customer action after the automated path was exhausted.' : caseData.status === 'RECOVERED' ? 'Recovered through the active execution path.' : 'The system is still processing the recovery workflow.'}
              </p>
            </CardContent>
          </Card>

          <Card className="bg-slate-50 border-dashed border-2">
            <CardHeader>
              <CardTitle className="text-sm flex items-center gap-2">
                <History className="w-4 h-4 text-slate-400" />
                Historical Evidence
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4 text-sm">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg bg-white border border-slate-200 p-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Similar cases</p>
                  <p className="mt-1 text-lg font-bold text-slate-900">{caseData.historical_evidence?.similar_cases ?? 'Not available'}</p>
                </div>
                <div className="rounded-lg bg-white border border-slate-200 p-3">
                  <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Recovery rate</p>
                  <p className="mt-1 text-lg font-bold text-slate-900">{caseData.historical_evidence?.historical_recovery_rate !== null && caseData.historical_evidence?.historical_recovery_rate !== undefined ? `${(caseData.historical_evidence.historical_recovery_rate * 100).toFixed(1)}%` : 'Not available'}</p>
                </div>
              </div>
              <div className="rounded-lg bg-white border border-slate-200 p-3">
                <p className="text-[10px] font-bold uppercase tracking-[0.2em] text-slate-400">Best strategy</p>
                <p className="mt-1 font-bold text-slate-900">{caseData.historical_evidence?.best_strategy ? caseData.historical_evidence.best_strategy.replace(/_/g, ' ') : 'Not available'}</p>
              </div>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
