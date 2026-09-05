'use client';

import * as React from 'react';
import Link from 'next/link';
import { usePathname, useRouter } from 'next/navigation';
import {
  LayoutDashboard,
  RefreshCcw,
  BarChart3,
  ChevronRight,
  Menu,
  X,
  Activity,
  ArrowUpRight
} from 'lucide-react';
import { cn } from '@/lib/utils';
import { Badge } from '@/components/ui/Badge';
import { useAuth } from '@/components/auth/AuthProvider';

const NAVIGATION = [
  { label: 'Overview', href: '/dashboard', icon: LayoutDashboard },
  { label: 'Recovery Cases', href: '/dashboard/cases', icon: Activity },
  { label: 'Analytics', href: '/dashboard/analytics', icon: BarChart3 },
];

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const { user, loading, signOutUser } = useAuth();
  const [isMobileMenuOpen, setIsMobileMenuOpen] = React.useState(false);

  React.useEffect(() => {
    if (!loading && !user) router.replace('/login');
  }, [loading, router, user]);

  React.useEffect(() => {
    if (!user) return;
    // Load route code while the current view is idle so sidebar navigation
    // feels immediate instead of waiting for the next page bundle.
    router.prefetch('/dashboard');
    router.prefetch('/dashboard/cases');
    router.prefetch('/dashboard/analytics');
  }, [router, user]);

  if (loading || !user) return <div className="min-h-screen bg-slate-50" />;

  return (
    <div className="flex min-h-screen bg-[#f7f8fb]">
      {/* Desktop Sidebar */}
      <aside className="hidden md:flex w-64 flex-col border-r border-slate-200/80 bg-white sticky top-0 h-screen">
        <div className="p-5">
          <Link href="/" className="flex items-center gap-2.5 mb-10 group">
            <div className="w-9 h-9 bg-slate-950 rounded-xl flex items-center justify-center transition-transform group-hover:scale-105 shadow-sm">
              <RefreshCcw className="w-5 h-5 text-white" />
            </div>
            <span className="font-display font-bold text-xl tracking-tight text-slate-950">Revenue</span>
          </Link>

          <nav className="space-y-1">
            {NAVIGATION.map((item) => {
              const isActive = pathname === item.href || (item.href !== '/dashboard' && pathname.startsWith(item.href));
              return (
                <Link
                  key={item.label}
                  href={item.href}
                  className={cn(
                    "flex items-center justify-between px-3 py-2.5 rounded-xl text-sm font-medium transition-all",
                    isActive
                      ? "bg-slate-950 text-white shadow-sm shadow-slate-200"
                      : "text-slate-500 hover:text-slate-900 hover:bg-slate-50"
                  )}
                >
                  <div className="flex items-center gap-3">
                    <item.icon className={cn("w-4 h-4", isActive ? "text-white" : "text-slate-400")} />
                    {item.label}
                  </div>
                  {isActive && <ChevronRight className="w-3 h-3 text-slate-300" />}
                </Link>
              );
            })}
          </nav>
        </div>

        <div className="mt-auto p-5 border-t border-slate-100">
          <div className="bg-slate-50 rounded-2xl p-4 border border-slate-100">
            <p className="text-[10px] font-bold text-slate-400 uppercase tracking-widest mb-2">System Health</p>
            <div className="flex items-center gap-2">
              <div className="w-2 h-2 rounded-full bg-emerald-500" />
              <span className="text-xs font-semibold text-slate-600">Operational</span>
            </div>
            <button onClick={signOutUser} className="mt-4 w-full text-left text-xs font-semibold text-slate-500 transition-colors hover:text-slate-900">
              Sign out
            </button>
          </div>
        </div>
      </aside>

      {/* Mobile Top Bar */}
      <div className="md:hidden fixed top-0 w-full z-50 bg-white border-b border-slate-200 px-4 py-3 flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2">
          <div className="w-8 h-8 bg-slate-900 rounded-lg flex items-center justify-center">
            <RefreshCcw className="w-5 h-5 text-white" />
          </div>
          <span className="font-display font-bold text-lg tracking-tight">Revenue</span>
        </Link>
        <button
          onClick={() => setIsMobileMenuOpen(!isMobileMenuOpen)}
          className="p-2 text-slate-500"
        >
          {isMobileMenuOpen ? <X className="w-6 h-6" /> : <Menu className="w-6 h-6" />}
        </button>
      </div>

      {/* Mobile Menu Overlay */}
      {isMobileMenuOpen && (
        <div className="md:hidden fixed inset-0 z-40 bg-white pt-20 px-6 space-y-6">
          <nav className="space-y-4">
            {NAVIGATION.map((item) => {
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.label}
                  href={item.href}
                  onClick={() => setIsMobileMenuOpen(false)}
                  className={cn(
                    "flex items-center gap-3 text-lg font-semibold",
                    isActive ? "text-slate-900" : "text-slate-400"
                  )}
                >
                  <item.icon className="w-5 h-5" />
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
      )}

      {/* Main Content */}
      <main className="flex-1 w-full pt-16 md:pt-0 overflow-y-auto">
        <div className="max-w-[1440px] mx-auto px-5 py-6 md:px-8 md:py-8">
          {children}
        </div>
      </main>
    </div>
  );
}
