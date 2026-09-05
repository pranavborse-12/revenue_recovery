'use client';

import * as React from 'react';
import { api, type BatchAnalytics } from '@/lib/api';
import { formatCurrency, formatCompactNumber, cn } from '@/lib/utils';
import { Card, CardHeader, CardTitle, CardContent, CardDescription } from '@/components/ui/Card';
import { Button } from '@/components/ui/Button';
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
  PieChart,
  Pie,
  Cell,
} from 'recharts';
import {
  RefreshCcw,
  TrendingUp,
  Target,
  Zap,
  Mail,
  Brain,
  ShieldAlert,
  ChevronRight,
  Link as LinkIcon
} from 'lucide-react';

export default function AnalyticsPage() {
  const [batch, setBatch] = React.useState<BatchAnalytics | null>(null);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const fetchData = React.useCallback(async () => {
    setIsLoading(true);
    try {
      setBatch(await api.getBatchAnalytics());
      setError(null);
    } catch (err) {
      console.error(err);
      setError('Analytics could not be loaded. Please try again.');
    } finally {
      setIsLoading(false);
    }
  }, []);

  React.useEffect(() => {
    const timer = setTimeout(() => fetchData(), 0);
    return () => clearTimeout(timer);
  }, [fetchData]);

  const pieData = [
    { name: 'Recovered', value: batch?.recovered_cases || 0, color: '#10b981' },
    { name: 'Escalated', value: batch?.escalated_cases || 0, color: '#3b82f6' },
    { name: 'Stopped', value: batch?.stopped_cases || 0, color: '#ef4444' },
  ];

  const aiData = [
    { name: 'Decisions', value: batch?.ai_decisions || 0, color: '#6366f1' },
    { name: 'Executed', value: batch?.ai_decisions_executed || 0, color: '#10b981' },
    { name: 'Policy Rejections', value: batch?.ai_policy_rejections || 0, color: '#f59e0b' },
  ];

  if (isLoading && !batch) {
    return <div className="animate-pulse space-y-8">
      <div className="h-8 w-48 bg-slate-200 rounded" />
      <div className="grid grid-cols-1 md:grid-cols-3 gap-8">
        {[...Array(3)].map((_, i) => <div key={i} className="h-32 bg-slate-100 rounded-xl" />)}
      </div>
      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        <div className="h-96 bg-slate-100 rounded-xl" />
        <div className="h-96 bg-slate-100 rounded-xl" />
      </div>
    </div>;
  }

  if (error && !batch) {
    return (
      <div className="flex min-h-[50vh] flex-col items-center justify-center gap-4 text-center">
        <p className="text-sm text-slate-500">{error}</p>
        <Button variant="outline" onClick={fetchData}>Try again</Button>
      </div>
    );
  }

  return (
    <div className="space-y-8 pb-20">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight">Recovery Analytics</h1>
          <p className="text-slate-500">Detailed performance metrics and AI decision insights.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => fetchData()} className="gap-2">
          <RefreshCcw className={cn("w-4 h-4", isLoading && "animate-spin")} />
          Refresh Stats
        </Button>
      </div>

      {/* High Level Stats */}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        <Card>
          <CardContent className="p-6 flex items-center justify-between">
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Recovery Rate</p>
              <h2 className="text-3xl font-bold text-emerald-600">{((batch?.recovery_rate || 0) * 100).toFixed(1)}%</h2>
            </div>
            <div className="w-12 h-12 bg-emerald-50 rounded-full flex items-center justify-center">
              <Target className="w-6 h-6 text-emerald-600" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6 flex items-center justify-between">
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Total Recovered</p>
              <h2 className="text-3xl font-bold text-slate-900">{formatCurrency(batch?.recovered_revenue || 0)}</h2>
            </div>
            <div className="w-12 h-12 bg-slate-100 rounded-full flex items-center justify-center">
              <TrendingUp className="w-6 h-6 text-slate-900" />
            </div>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-6 flex items-center justify-between">
            <div className="space-y-1">
              <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">Cases Processed</p>
              <h2 className="text-3xl font-bold text-slate-900">{formatCompactNumber(batch?.cases_processed || 0)}</h2>
            </div>
            <div className="w-12 h-12 bg-blue-50 rounded-full flex items-center justify-center">
              <Zap className="w-6 h-6 text-blue-600" />
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-8">
        {/* Outcome Distribution */}
        <Card>
          <CardHeader>
            <CardTitle>Case Outcomes</CardTitle>
            <CardDescription>Distribution of processed recovery cases.</CardDescription>
          </CardHeader>
          <CardContent className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <PieChart>
                <Pie
                  data={pieData}
                  cx="50%"
                  cy="50%"
                  innerRadius={60}
                  outerRadius={100}
                  paddingAngle={5}
                  dataKey="value"
                >
                  {pieData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Pie>
                <Tooltip />
              </PieChart>
            </ResponsiveContainer>
            <div className="flex justify-center gap-6 mt-4">
              {pieData.map((item) => (
                <div key={item.name} className="flex items-center gap-2">
                  <div className="w-3 h-3 rounded-full" style={{ backgroundColor: item.color }} />
                  <span className="text-xs font-bold text-slate-600">{item.name}</span>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>

        {/* AI Performance */}
        <Card>
          <CardHeader>
            <CardTitle>Intelligence Layer</CardTitle>
            <CardDescription>AI decision performance and policy validation.</CardDescription>
          </CardHeader>
          <CardContent className="h-[300px]">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={aiData} margin={{ top: 20, right: 30, left: 0, bottom: 0 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#f1f5f9" />
                <XAxis dataKey="name" axisLine={false} tickLine={false} tick={{ fontSize: 12, fontWeight: 600, fill: '#64748b' }} dy={10} />
                <YAxis axisLine={false} tickLine={false} tick={{ fontSize: 12, fill: '#94a3b8' }} />
                <Tooltip
                  cursor={{ fill: '#f8fafc' }}
                  contentStyle={{ borderRadius: '12px', border: '1px solid #e2e8f0', boxShadow: '0 4px 6px -1px rgb(0 0 0 / 0.1)' }}
                />
                <Bar dataKey="value" radius={[4, 4, 0, 0]}>
                  {aiData.map((entry, index) => (
                    <Cell key={`cell-${index}`} fill={entry.color} />
                  ))}
                </Bar>
              </BarChart>
            </ResponsiveContainer>
          </CardContent>
        </Card>

        {/* Operational Volume */}
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>System Throughput</CardTitle>
            <CardDescription>Operational activity across all channels.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="grid grid-cols-2 md:grid-cols-4 gap-8">
              {[
                { label: 'Retries Executed', value: batch?.retries_executed, icon: RefreshCcw, color: 'text-blue-600', bg: 'bg-blue-50' },
                { label: 'Payment Links', value: batch?.payment_links_created, icon: LinkIcon, color: 'text-emerald-600', bg: 'bg-emerald-50' },
                { label: 'Emails Sent', value: batch?.emails_sent, icon: Mail, color: 'text-slate-600', bg: 'bg-slate-50' },
                { label: 'AI Decisions', value: batch?.ai_decisions, icon: Brain, color: 'text-purple-600', bg: 'bg-purple-50' },
              ].map((item, i) => (
                <div key={i} className="space-y-3">
                  <div className={cn("w-10 h-10 rounded-lg flex items-center justify-center", item.bg)}>
                    <item.icon className={cn("w-5 h-5", item.color)} />
                  </div>
                  <div className="space-y-0.5">
                    <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest">{item.label}</p>
                    <h3 className="text-2xl font-bold text-slate-900">{formatCompactNumber(item.value || 0)}</h3>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-12 p-6 rounded-2xl bg-slate-900 text-white flex items-center justify-between">
              <div className="space-y-1">
                <p className="text-xs font-bold text-slate-500 uppercase tracking-widest">Policy Safety</p>
                <div className="flex items-center gap-3">
                  <ShieldAlert className="w-5 h-5 text-amber-500" />
                  <h3 className="text-xl font-bold">{batch?.ai_policy_rejections} Decisions Rejected by Policy</h3>
                </div>
              </div>
              <Button variant="ghost" className="text-slate-400 hover:text-white hover:bg-slate-800">
                View Policy Logs
                <ChevronRight className="ml-2 w-4 h-4" />
              </Button>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
