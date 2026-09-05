'use client';

import * as React from 'react';
import { api, type RecoveryStats, type RecoveryCase } from '@/lib/api';
import { formatCurrency, formatCompactNumber, formatProbability, cn } from '@/lib/utils';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import {
  ArrowUpRight,
  RefreshCcw,
  AlertCircle,
  CheckCircle2,
  ChevronRight,
  TrendingUp,
  BarChart2,
  Activity
} from 'lucide-react';
import Link from 'next/link';

export default function DashboardOverview() {
  const [stats, setStats] = React.useState<RecoveryStats | null>(null);
  const [recentCases, setRecentCases] = React.useState<RecoveryCase[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const fetchData = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const [statsData, casesData] = await Promise.all([
        api.getStats(),
        api.getCases(undefined, 5)
      ]);
      setStats(statsData);
      setRecentCases(casesData);
      setError(null);
    } catch (err) {
      console.error(err);
      setError('Failed to load dashboard data. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    const timer = setTimeout(() => fetchData(), 0);
    return () => clearTimeout(timer);
  }, [fetchData]);

  if (isLoading && !stats) {
    return (
      <div className="space-y-8 animate-pulse">
        <div className="flex justify-between items-end">
          <div className="space-y-2">
            <div className="h-8 w-48 bg-slate-200 rounded" />
            <div className="h-4 w-64 bg-slate-100 rounded" />
          </div>
          <div className="h-10 w-24 bg-slate-200 rounded" />
        </div>
        <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
          {[...Array(4)].map((_, i) => <div key={i} className="h-32 bg-slate-100 rounded-xl" />)}
        </div>
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          <div className="lg:col-span-2 h-96 bg-slate-100 rounded-xl" />
          <div className="h-96 bg-slate-100 rounded-xl" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-[60vh] text-center space-y-4">
        <div className="w-16 h-16 bg-red-50 text-red-600 rounded-full flex items-center justify-center">
          <AlertCircle className="w-8 h-8" />
        </div>
        <div className="space-y-1">
          <h2 className="text-xl font-bold">Something went wrong</h2>
          <p className="text-slate-500">{error}</p>
        </div>
        <Button onClick={() => fetchData()}>Retry Refresh</Button>
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
        <div className="space-y-1.5">
          <div className="flex items-center gap-2 text-xs font-semibold uppercase tracking-[0.16em] text-emerald-600">
            <span className="h-2 w-2 rounded-full bg-emerald-500" /> Live performance
          </div>
          <h1 className="text-2xl md:text-3xl font-bold tracking-tight">Recovery overview</h1>
          <p className="text-sm text-slate-500">A clear picture of revenue recovery and cases that need attention.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => fetchData()} className="gap-2">
          <RefreshCcw className={cn("w-4 h-4", isLoading && "animate-spin")} />
          Refresh Data
        </Button>
      </div>

      {/* Primary Metrics */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-4">
        <Card className="border-emerald-100/80 shadow-sm">
          <CardContent className="p-5 space-y-5">
            <div className="flex items-center justify-between">
              <div className="p-2.5 bg-emerald-50 text-emerald-600 rounded-xl">
                <TrendingUp className="w-5 h-5" />
              </div>
              <Badge variant="success">+{stats?.recovery_rate ? (stats.recovery_rate * 100).toFixed(1) : 0}% Rate</Badge>
            </div>
            <div className="space-y-1">
              <p className="text-[11px] font-bold text-slate-400 uppercase tracking-[0.14em]">Recovered revenue</p>
              <h2 className="text-[28px] leading-none font-bold text-emerald-600">{formatCurrency(stats?.total_recovered_revenue || 0)}</h2>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5 space-y-5">
            <div className="flex items-center justify-between">
              <div className="p-2.5 bg-slate-100 text-slate-600 rounded-xl">
                <BarChart2 className="w-5 h-5" />
              </div>
              <p className="text-xs font-semibold text-slate-500">{formatCompactNumber(stats?.total_failed_payments || 0)} failures</p>
            </div>
            <div className="space-y-1">
              <p className="text-[11px] font-bold text-slate-400 uppercase tracking-[0.14em]">Revenue at risk</p>
              <h2 className="text-[28px] leading-none font-bold text-slate-900">{formatCurrency(stats?.total_revenue_at_risk || 0)}</h2>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5 space-y-5">
            <div className="flex items-center justify-between">
              <div className="p-2.5 bg-blue-50 text-blue-600 rounded-xl">
                <Activity className="w-5 h-5" />
              </div>
              <Badge variant="info">{stats?.active_recovery_cases} Active</Badge>
            </div>
            <div className="space-y-1">
              <p className="text-[11px] font-bold text-slate-400 uppercase tracking-[0.14em]">Recovery success</p>
              <h2 className="text-[28px] leading-none font-bold text-slate-900">{stats?.recovered_cases} <span className="text-sm font-medium text-slate-400">cases</span></h2>
            </div>
          </CardContent>
        </Card>

        <Card>
          <CardContent className="p-5 space-y-5">
            <div className="flex items-center justify-between">
              <div className="p-2.5 bg-amber-50 text-amber-600 rounded-xl">
                <AlertCircle className="w-5 h-5" />
              </div>
            </div>
            <div className="space-y-1">
              <p className="text-[11px] font-bold text-slate-400 uppercase tracking-[0.14em]">Customer action</p>
              <h2 className="text-[28px] leading-none font-bold text-slate-900">{stats?.awaiting_customer_cases} <span className="text-sm font-medium text-slate-400">pending</span></h2>
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 xl:grid-cols-[minmax(0,1fr)_360px] gap-5 items-start">
        {/* Recent Cases Table */}
        <Card className="overflow-hidden">
          <CardHeader className="flex flex-row items-center justify-between p-5 md:p-6 pb-4 border-b border-slate-100">
            <div className="space-y-1">
              <CardTitle>Recent Recovery Cases</CardTitle>
              <CardDescription>The latest payment failures entering the system.</CardDescription>
            </div>
            <Link href="/dashboard/cases">
              <Button variant="ghost" size="sm" className="gap-2">
                View all cases
                <ChevronRight className="w-4 h-4" />
              </Button>
            </Link>
          </CardHeader>
          <CardContent className="p-3 md:p-4">
            {recentCases.length === 0 ? (
              <div className="py-12 text-center space-y-3">
                <div className="w-12 h-12 bg-slate-50 rounded-full flex items-center justify-center mx-auto">
                  <CheckCircle2 className="w-6 h-6 text-slate-300" />
                </div>
                <p className="text-sm text-slate-500">No active recovery cases yet.</p>
              </div>
            ) : (
              <div className="space-y-1">
                <div className="hidden lg:grid grid-cols-[minmax(190px,1.4fr)_100px_110px_minmax(135px,1fr)_28px] gap-4 px-3 pb-2 text-[10px] font-bold uppercase tracking-[0.15em] text-slate-400">
                  <span>Case</span><span className="text-right">Amount</span><span className="text-right">Likelihood</span><span>Recommendation</span><span />
                </div>
                {recentCases.map((item) => (
                  <Link
                    key={item.id}
                    href={`/dashboard/cases/${item.id}`}
                    className="grid grid-cols-[minmax(0,1fr)_auto] lg:grid-cols-[minmax(190px,1.4fr)_100px_110px_minmax(135px,1fr)_28px] items-center gap-4 p-3 rounded-xl transition-all hover:bg-slate-50 group"
                  >
                    <div className="flex items-center gap-4">
                      <div className="w-10 h-10 rounded-lg bg-slate-100 flex items-center justify-center group-hover:bg-white border border-transparent group-hover:border-slate-200 shadow-sm transition-all">
                        <Activity className="w-5 h-5 text-slate-500" />
                      </div>
                      <div className="space-y-0.5">
                        <div className="flex items-center gap-2">
                          <p className="text-sm font-bold text-slate-900">CASE-{item.id.toString().padStart(4, '0')}</p>
                          <Badge variant={
                            item.status === 'RECOVERED' ? 'success' :
                            item.status === 'EXHAUSTED' ? 'error' :
                            item.status === 'AWAITING_CUSTOMER' ? 'warning' : 'info'
                          } className="lg:hidden">
                            {item.status === 'AWAITING_CUSTOMER' ? 'Action needed' : item.status.replace(/_/g, ' ')}
                          </Badge>
                        </div>
                        <p className="text-xs text-slate-500 uppercase font-bold tracking-tight">{item.failure_category.replace(/_/g, ' ')}</p>
                      </div>
                    </div>
                    <div className="contents">
                      <div className="text-right hidden lg:block">
                        <p className="text-sm font-bold text-slate-900">{formatCurrency(item.amount)}</p>
                        <p className="text-xs text-slate-400 font-medium">Attempt {item.attempt_count}</p>
                      </div>
                      <div className="hidden lg:block text-right">
                        <p className="text-sm font-bold text-slate-900">{formatProbability(item.recovery_probability)}</p>
                      </div>
                      <div className="hidden lg:flex items-center gap-2 min-w-0">
                        <span className="text-xs font-semibold text-slate-600 truncate">{item.ai_recommendation || 'No recommendation'}</span>
                        <Badge variant={
                        item.status === 'RECOVERED' ? 'success' :
                        item.status === 'EXHAUSTED' ? 'error' :
                        item.status === 'AWAITING_CUSTOMER' ? 'warning' : 'info'
                        } className="shrink-0">{item.status === 'AWAITING_CUSTOMER' ? 'Action needed' : item.status.replace(/_/g, ' ')}</Badge>
                      </div>
                      <ChevronRight className="w-4 h-4 text-slate-300 group-hover:text-slate-900 transition-colors" />
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* System Summary Card */}
        <div className="space-y-6">
          <Card className="bg-slate-950 text-white overflow-hidden relative border-slate-800 shadow-lg shadow-slate-300/30">
            <div className="absolute top-0 right-0 w-32 h-32 bg-emerald-500/10 blur-3xl" />
            <CardHeader className="p-6 pb-3">
              <CardTitle className="text-white">System Intelligence</CardTitle>
              <CardDescription className="text-slate-400">Recovery performance summary</CardDescription>
            </CardHeader>
            <CardContent className="p-6 pt-3 space-y-6">
              <div className="space-y-2">
                <div className="flex justify-between text-xs font-bold uppercase tracking-widest text-slate-500">
                  <span>Recovery Success</span>
                  <span className="text-emerald-400">{stats?.recovery_rate ? (stats.recovery_rate * 100).toFixed(0) : 0}%</span>
                </div>
                <div className="h-1.5 w-full bg-slate-800 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-emerald-500 transition-all duration-1000"
                    style={{ width: `${(stats?.recovery_rate || 0) * 100}%` }}
                  />
                </div>
              </div>
              <div className="space-y-4 pt-4 border-t border-slate-800">
                <div className="flex items-center gap-3">
                  <div className="w-2 h-2 rounded-full bg-emerald-500" />
                  <p className="text-sm font-medium text-slate-300">{stats?.recovered_cases} Successful Recoveries</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-2 h-2 rounded-full bg-slate-700" />
                  <p className="text-sm font-medium text-slate-300">{stats?.exhausted_cases} Exhausted Attempts</p>
                </div>
                <div className="flex items-center gap-3">
                  <div className="w-2 h-2 rounded-full bg-blue-500" />
                  <p className="text-sm font-medium text-slate-300">{stats?.awaiting_customer_cases} pending customer action</p>
                </div>
              </div>
              <Link href="/dashboard/analytics">
                <Button variant="ghost" className="w-full text-slate-300 hover:text-white hover:bg-slate-800 justify-between group">
                  Detailed Analytics
                  <ArrowUpRight className="w-4 h-4 transition-transform group-hover:translate-x-0.5 group-hover:-translate-y-0.5" />
                </Button>
              </Link>
            </CardContent>
          </Card>

          <Card className="border-slate-200/90">
            <CardHeader className="p-5 pb-2">
              <CardTitle className="text-sm">Priority queue</CardTitle>
            </CardHeader>
            <CardContent className="p-5 pt-2 space-y-2">
              <Link href="/dashboard/cases?status_filter=AWAITING_CUSTOMER">
                <Button variant="outline" className="w-full justify-between text-left h-auto py-3">
                  <div className="space-y-0.5">
                    <p className="text-sm font-bold">Review Pending Actions</p>
                    <p className="text-xs text-slate-500">Customers awaiting assistance</p>
                  </div>
                  <Badge variant="warning">{stats?.awaiting_customer_cases}</Badge>
                </Button>
              </Link>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
