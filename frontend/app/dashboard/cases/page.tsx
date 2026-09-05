'use client';

import * as React from 'react';
import { useSearchParams, useRouter } from 'next/navigation';
import { api, type RecoveryCase, type RecoveryStatus } from '@/lib/api';
import { formatCurrency, formatDate, cn } from '@/lib/utils';
import {
  Table,
  TableHeader,
  TableBody,
  TableHead,
  TableRow,
  TableCell
} from '@/components/ui/Table';
import { Badge } from '@/components/ui/Badge';
import { Button } from '@/components/ui/Button';
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from '@/components/ui/Card';
import {
  Search,
  Filter,
  RefreshCcw,
  ChevronRight,
  ExternalLink,
  MoreHorizontal,
  ChevronLeft,
  Activity
} from 'lucide-react';
import Link from 'next/link';

const STATUS_OPTIONS: { label: string; value: RecoveryStatus | 'ALL' }[] = [
  { label: 'All Cases', value: 'ALL' },
  { label: 'In Progress', value: 'IN_PROGRESS' },
  { label: 'Awaiting Customer', value: 'AWAITING_CUSTOMER' },
  { label: 'Recovered', value: 'RECOVERED' },
  { label: 'Exhausted', value: 'EXHAUSTED' },
  { label: 'Cancelled', value: 'CANCELLED' },
];

function CasesList({ refreshToken }: { refreshToken: number }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const statusFilter = searchParams.get('status_filter') || 'ALL';
  const limitParam = parseInt(searchParams.get('limit') || '50');

  const [cases, setCases] = React.useState<RecoveryCase[]>([]);
  const [isLoading, setIsLoading] = React.useState(true);
  const [error, setError] = React.useState<string | null>(null);

  const fetchCases = React.useCallback(async () => {
    setIsLoading(true);
    try {
      const data = await api.getCases(
        statusFilter === 'ALL' ? undefined : statusFilter,
        limitParam
      );
      setCases(data);
      setError(null);
    } catch (err) {
      console.error(err);
      setError('Failed to load recovery cases.');
    } finally {
      setIsLoading(false);
    }
  }, [statusFilter, limitParam]);

  React.useEffect(() => {
    const timer = setTimeout(() => fetchCases(), 0);
    return () => clearTimeout(timer);
  }, [fetchCases, refreshToken]);

  const handleStatusChange = (status: string) => {
    const params = new URLSearchParams(searchParams.toString());
    if (status === 'ALL') {
      params.delete('status_filter');
    } else {
      params.set('status_filter', status);
    }
    router.push(`?${params.toString()}`);
  };

  return (
    <Card>
      <CardHeader className="pb-4">
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex flex-wrap items-center gap-2">
            {STATUS_OPTIONS.map((option) => (
              <button
                key={option.value}
                onClick={() => handleStatusChange(option.value)}
                className={cn(
                  "px-3 py-1.5 text-xs font-semibold rounded-full transition-all border",
                  statusFilter === option.value
                    ? "bg-slate-900 text-white border-slate-900"
                    : "bg-white text-slate-500 border-slate-200 hover:border-slate-300"
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <div className="flex items-center gap-2 text-xs font-medium text-slate-400">
            <Activity className="w-3.5 h-3.5" />
            <span>{cases.length} cases found</span>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-0">
        <Table>
          <TableHeader>
            <TableRow className="bg-slate-50/50">
              <TableHead className="w-[100px]">Case ID</TableHead>
              <TableHead>Amount</TableHead>
              <TableHead>Failure Category</TableHead>
              <TableHead>Current Strategy</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Attempts</TableHead>
              <TableHead className="text-right">Created</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isLoading ? (
              [...Array(5)].map((_, i) => (
                <TableRow key={i}>
                  {[...Array(7)].map((_, j) => (
                    <TableCell key={j}><div className="h-4 bg-slate-100 rounded animate-pulse" /></TableCell>
                  ))}
                </TableRow>
              ))
            ) : error ? (
              <TableRow>
                <TableCell colSpan={7} className="h-64 text-center text-sm text-slate-500">
                  <div className="space-y-3">
                    <p>{error}</p>
                    <Button variant="outline" size="sm" onClick={fetchCases}>Try again</Button>
                  </div>
                </TableCell>
              </TableRow>
            ) : cases.length === 0 ? (
              <TableRow>
                <TableCell colSpan={7} className="h-64 text-center">
                  <div className="flex flex-col items-center justify-center space-y-3">
                    <div className="w-12 h-12 bg-slate-50 rounded-full flex items-center justify-center">
                      <Activity className="w-6 h-6 text-slate-200" />
                    </div>
                    <div className="space-y-1">
                      <p className="text-sm font-bold text-slate-900">No cases found</p>
                      <p className="text-xs text-slate-500">Try adjusting your filters or check back later.</p>
                    </div>
                  </div>
                </TableCell>
              </TableRow>
            ) : (
              cases.map((item) => (
                <TableRow
                  key={item.id}
                  className="cursor-pointer group"
                  onMouseEnter={() => router.prefetch(`/dashboard/cases/${item.id}`)}
                  onClick={() => router.push(`/dashboard/cases/${item.id}`)}
                >
                  <TableCell className="font-bold text-slate-900">
                    CASE-{item.id.toString().padStart(4, '0')}
                  </TableCell>
                  <TableCell className="font-bold">
                    {formatCurrency(item.amount)}
                  </TableCell>
                  <TableCell>
                    <span className="text-xs font-bold text-slate-500 uppercase tracking-tight">
                      {item.failure_category.replace(/_/g, ' ')}
                    </span>
                  </TableCell>
                  <TableCell>
                    <span className="text-slate-600 font-medium">
                      {item.current_strategy.replace(/_/g, ' ')}
                    </span>
                  </TableCell>
                  <TableCell>
                    <Badge variant={
                      item.status === 'RECOVERED' ? 'success' :
                      item.status === 'EXHAUSTED' ? 'error' :
                      item.status === 'AWAITING_CUSTOMER' ? 'warning' : 'info'
                    }>
                      {item.status.replace(/_/g, ' ')}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    <div className="flex items-center gap-2">
                      <span className="text-slate-900 font-bold">{item.attempt_count}</span>
                      <div className="flex gap-0.5">
                        {[...Array(3)].map((_, i) => (
                          <div
                            key={i}
                            className={cn(
                              "w-1 h-1 rounded-full",
                              i < item.attempt_count ? "bg-slate-900" : "bg-slate-200"
                            )}
                          />
                        ))}
                      </div>
                    </div>
                  </TableCell>
                  <TableCell className="text-right text-slate-500 text-xs font-medium">
                    {formatDate(item.created_at)}
                  </TableCell>
                </TableRow>
              ))
            )}
          </TableBody>
        </Table>
      </CardContent>
    </Card>
  );
}

export default function CasesPage() {
  const [refreshToken, setRefreshToken] = React.useState(0);

  return (
    <div className="space-y-8">
      <div className="flex flex-col md:flex-row md:items-end justify-between gap-4">
        <div className="space-y-1">
          <h1 className="text-3xl font-bold tracking-tight">Recovery Cases</h1>
          <p className="text-slate-500">Manage and track individual payment recovery workflows.</p>
        </div>
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" className="gap-2" onClick={() => setRefreshToken((value) => value + 1)}>
            <RefreshCcw className="w-4 h-4" />
            Refresh
          </Button>
        </div>
      </div>

      <React.Suspense fallback={<Card className="h-96 animate-pulse bg-slate-50" />}>
        <CasesList refreshToken={refreshToken} />
      </React.Suspense>
    </div>
  );
}
