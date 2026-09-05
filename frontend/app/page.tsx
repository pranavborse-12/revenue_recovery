'use client';

import * as React from 'react';
import Link from 'next/link';
import Image from 'next/image';
import { motion } from 'motion/react';
import {
  ArrowRight,
  ShieldCheck,
  Zap,
  BarChart3,
  RefreshCcw,
  Link as LinkIcon,
  Users,
  Eye,
  CheckCircle2,
  Lock,
  ChevronRight,
  Sparkles
} from 'lucide-react';
import { Button } from '@/components/ui/Button';
import { Card, CardContent } from '@/components/ui/Card';
import { Badge } from '@/components/ui/Badge';
import { cn } from '@/lib/utils';

const NAV_LINKS = [
  { label: 'Product', href: '#product' },
  { label: 'How it works', href: '#how-it-works' },
  { label: 'Intelligence', href: '#intelligence' },
  { label: 'Analytics', href: '#analytics' },
];

export default function LandingPage() {
  const [isScrolled, setIsScrolled] = React.useState(false);

  React.useEffect(() => {
    const handleScroll = () => setIsScrolled(window.scrollY > 10);
    window.addEventListener('scroll', handleScroll);
    return () => window.removeEventListener('scroll', handleScroll);
  }, []);

  return (
    <div className="flex min-h-screen flex-col bg-white">
      {/* Navigation */}
      <nav className={cn(
        "fixed top-0 z-50 w-full transition-all duration-300 border-b",
        isScrolled ? "bg-white/80 backdrop-blur-md border-slate-200 py-3" : "bg-transparent border-transparent py-5"
      )}>
        <div className="container mx-auto px-6 flex items-center justify-between">
          <div className="flex items-center gap-8">
            <Link href="/" className="flex items-center gap-2">
              <div className="w-8 h-8 bg-slate-900 rounded-lg flex items-center justify-center">
                <RefreshCcw className="w-5 h-5 text-white" />
              </div>
              <span className="font-display font-bold text-xl tracking-tight">RevFlow</span>
            </Link>
            <div className="hidden md:flex items-center gap-6">
              {NAV_LINKS.map(link => (
                <Link
                  key={link.label}
                  href={link.href}
                  className="text-sm font-medium text-slate-600 hover:text-slate-900 transition-colors"
                >
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <Link href="/login">
              <Button variant="primary" size="sm" className="hidden sm:inline-flex">
                Open Dashboard
              </Button>
            </Link>
          </div>
        </div>
      </nav>

      <main className="flex-grow pt-32">
        {/* Hero Section */}
        <section className="container mx-auto px-6 pb-20">
          <div className="max-w-4xl mx-auto text-center space-y-8">
            <motion.div
              initial={{ opacity: 0, y: 20 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ duration: 0.6 }}
            >
              <Badge variant="info" className="px-3 py-1 mb-6">
                Now with AI Intelligence
              </Badge>
              <h1 className="text-5xl md:text-7xl font-display font-bold leading-[1.1] text-slate-950 tracking-tight text-balance">
                Turn failed payments into <span className="text-slate-500">recovered revenue.</span>
              </h1>
              <p className="mt-8 text-xl text-slate-600 max-w-2xl mx-auto leading-relaxed">
                Automatically detect, understand, and recover failed payments with intelligent retry strategies and customer-led recovery workflows.
              </p>
              <div className="mt-10 flex flex-wrap items-center justify-center gap-4">
                <Link href="/login">
                  <Button size="lg" className="h-14 px-8 rounded-xl group">
                    Open Dashboard
                    <ArrowRight className="ml-2 w-5 h-5 transition-transform group-hover:translate-x-1" />
                  </Button>
                </Link>
                <Button variant="outline" size="lg" className="h-14 px-8 rounded-xl">
                  See How It Works
                </Button>
              </div>
            </motion.div>

            {/* Product Preview */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 40 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              transition={{ duration: 0.8, delay: 0.2 }}
              className="mt-20 relative"
            >
              <div className="relative rounded-2xl border border-slate-200 bg-slate-50 p-2 shadow-2xl overflow-hidden">
                <div className="rounded-xl border border-slate-200 bg-white shadow-sm overflow-hidden">
                  <div className="h-12 border-b border-slate-100 bg-slate-50/50 flex items-center px-4 gap-2">
                    <div className="w-3 h-3 rounded-full bg-slate-200" />
                    <div className="w-3 h-3 rounded-full bg-slate-200" />
                    <div className="w-3 h-3 rounded-full bg-slate-200" />
                  </div>
                  <div className="p-8 space-y-8 text-left">
                    <div className="grid grid-cols-1 md:grid-cols-4 gap-6">
                      {[
                        { label: 'Recovered Revenue', value: '₹30,00,000', change: '+12%', color: 'text-emerald-600' },
                        { label: 'Revenue at Risk', value: '₹50,00,000', change: '-4%', color: 'text-slate-900' },
                        { label: 'Recovery Rate', value: '75%', change: '+2.4%', color: 'text-slate-900' },
                        { label: 'Active Cases', value: '4', change: 'New', color: 'text-slate-900' },
                      ].map((stat, i) => (
                        <div key={i} className="space-y-2">
                          <p className="text-xs font-semibold uppercase tracking-wider text-slate-400">{stat.label}</p>
                          <div className="flex items-baseline gap-2">
                            <span className={cn("text-2xl font-bold tracking-tight", stat.color)}>{stat.value}</span>
                            <span className="text-[10px] font-bold text-emerald-500 bg-emerald-50 px-1.5 py-0.5 rounded">{stat.change}</span>
                          </div>
                        </div>
                      ))}
                    </div>
                    <div className="space-y-4">
                      <p className="text-sm font-semibold text-slate-900">Recent Recovery Activity</p>
                      <div className="space-y-3">
                        {[
                          { id: 'REC-1024', customer: 'Acme Corp', amount: '₹50,000', status: 'Recovered', time: '2m ago' },
                          { id: 'REC-1023', customer: 'Globex Inc', amount: '₹1,20,000', status: 'In Progress', time: '15m ago' },
                          { id: 'REC-1022', customer: 'Soylent Corp', amount: '₹25,000', status: 'Recovered', time: '1h ago' },
                        ].map((item, i) => (
                          <div key={i} className="flex items-center justify-between p-4 rounded-xl border border-slate-100 bg-slate-50/30">
                            <div className="flex items-center gap-4">
                              <div className="w-10 h-10 rounded-lg bg-white border border-slate-100 flex items-center justify-center shadow-sm">
                                <Zap className={cn("w-5 h-5", item.status === 'Recovered' ? "text-emerald-500" : "text-blue-500")} />
                              </div>
                              <div>
                                <p className="text-sm font-bold text-slate-900">{item.customer}</p>
                                <p className="text-xs text-slate-500">{item.id} • {item.amount}</p>
                              </div>
                            </div>
                            <div className="text-right">
                              <Badge variant={item.status === 'Recovered' ? 'success' : 'info'} className="mb-1">{item.status}</Badge>
                              <p className="text-[10px] text-slate-400 font-medium">{item.time}</p>
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
              <div className="absolute -bottom-6 -left-6 w-32 h-32 bg-emerald-100/50 blur-3xl -z-10" />
              <div className="absolute -top-6 -right-6 w-32 h-32 bg-blue-100/50 blur-3xl -z-10" />
            </motion.div>
          </div>
        </section>

        {/* Problem Section */}
        <section className="bg-slate-50 py-24 border-y border-slate-200">
          <div className="container mx-auto px-6">
            <div className="max-w-3xl mx-auto text-center space-y-6">
              <h2 className="text-3xl md:text-4xl font-bold">A failed payment isn&apos;t lost revenue.</h2>
              <p className="text-lg text-slate-600 leading-relaxed">
                Bank declines, expired methods, and network errors shouldn&apos;t be the end of your customer relationship. We transform these failures into structured recovery opportunities.
              </p>
            </div>
            <div className="mt-16 grid grid-cols-1 md:grid-cols-3 gap-8">
              {[
                { title: 'Technical Failures', desc: 'Recover payments lost to temporary network blips or gateway errors.', icon: ShieldCheck },
                { title: 'Card Issues', desc: 'Identify expired methods or insufficient funds and guide customers through updates.', icon: RefreshCcw },
                { title: 'Bank Declines', desc: 'Understand decline codes and retry payments when success is most likely.', icon: Lock },
              ].map((item, i) => (
                <Card key={i} className="bg-white border-none shadow-none">
                  <CardContent className="p-8 space-y-4">
                    <div className="w-12 h-12 bg-slate-900 rounded-xl flex items-center justify-center">
                      <item.icon className="w-6 h-6 text-white" />
                    </div>
                    <h3 className="text-xl font-bold">{item.title}</h3>
                    <p className="text-slate-500 leading-relaxed">{item.desc}</p>
                  </CardContent>
                </Card>
              ))}
            </div>
          </div>
        </section>

        {/* How it works */}
        <section id="how-it-works" className="py-24">
          <div className="container mx-auto px-6">
            <div className="max-w-2xl mx-auto text-center space-y-4">
              <Badge variant="info">The Workflow</Badge>
              <h2 className="text-4xl font-bold">From failure to recovery.</h2>
            </div>
            <div className="mt-20 relative">
              <div className="hidden md:block absolute top-1/2 left-0 w-full h-px bg-slate-100 -z-10 translate-y-[-24px]" />
              <div className="grid grid-cols-1 md:grid-cols-4 gap-12">
                {[
                  { step: '01', title: 'Detect', desc: 'Instantly catch payment failures as they happen in your checkout or billing system.', icon: Eye },
                  { step: '02', title: 'Understand', desc: 'Analyze failure categories and classify risks using our recovery intelligence layer.', icon: Sparkles },
                  { step: '03', title: 'Recover', desc: 'Execute retries, send payment links, or escalate to customer-assisted workflows.', icon: RefreshCcw },
                  { step: '04', title: 'Measure', desc: 'Track recovered revenue and system performance in real-time.', icon: BarChart3 },
                ].map((item, i) => (
                  <div key={i} className="relative group">
                    <div className="w-12 h-12 bg-white border border-slate-200 rounded-xl flex items-center justify-center mb-6 group-hover:border-slate-400 transition-colors shadow-sm">
                      <item.icon className="w-5 h-5 text-slate-600" />
                    </div>
                    <div className="space-y-3">
                      <span className="text-[10px] font-bold text-slate-400 uppercase tracking-[0.2em]">{item.step}</span>
                      <h3 className="text-lg font-bold">{item.title}</h3>
                      <p className="text-sm text-slate-500 leading-relaxed">{item.desc}</p>
                    </div>
                  </div>
                ))}
              </div>
            </div>
          </div>
        </section>

        {/* Intelligence Section */}
        <section id="intelligence" className="py-24 bg-slate-900 text-white rounded-[2rem] mx-6 mb-24 overflow-hidden relative">
          <div className="absolute top-0 right-0 w-1/2 h-full bg-gradient-to-l from-slate-800/50 to-transparent pointer-events-none" />
          <div className="container mx-auto px-12 relative z-10">
            <div className="grid grid-cols-1 lg:grid-cols-2 gap-20 items-center">
              <div className="space-y-8">
                <Badge className="bg-emerald-500/10 text-emerald-400 border-emerald-500/20">Recovery Intelligence</Badge>
                <h2 className="text-4xl md:text-5xl font-bold leading-[1.2] text-white">Assistive AI for financial decisions.</h2>
                <p className="text-xl text-slate-400 leading-relaxed">
                  Our intelligence layer analyzes historical patterns and policy data to determine the most effective recovery path for every failed transaction.
                </p>
                <div className="space-y-4">
                  {[
                    'Intelligent Retry Scheduling',
                    'Failure Category Analysis',
                    'Customer Risk Profiling',
                    'Automated Strategy Selection',
                  ].map((feat, i) => (
                    <div key={i} className="flex items-center gap-3">
                      <CheckCircle2 className="w-5 h-5 text-emerald-500" />
                      <span className="font-medium text-slate-300">{feat}</span>
                    </div>
                  ))}
                </div>
              </div>
              <div className="bg-slate-800/50 border border-slate-700 p-8 rounded-2xl space-y-6">
                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-3">
                    <div className="w-2 h-2 rounded-full bg-emerald-500 animate-pulse" />
                    <span className="text-xs font-bold uppercase tracking-widest text-slate-500">Active Strategist</span>
                  </div>
                  <Badge className="bg-slate-700 text-slate-300 border-slate-600">Decision Engine v2.4</Badge>
                </div>
                <div className="space-y-4">
                  <div className="p-4 rounded-xl bg-slate-900 border border-slate-700/50">
                    <p className="text-xs text-slate-500 mb-2">Recommendation</p>
                    <p className="text-sm font-medium">Trigger <span className="text-emerald-400">Smart Retry</span> for Transaction #9482</p>
                  </div>
                  <div className="grid grid-cols-2 gap-4">
                    <div className="p-4 rounded-xl bg-slate-900 border border-slate-700/50">
                      <p className="text-xs text-slate-500 mb-1">Confidence</p>
                      <p className="text-xl font-bold text-white">94.2%</p>
                    </div>
                    <div className="p-4 rounded-xl bg-slate-900 border border-slate-700/50">
                      <p className="text-xs text-slate-500 mb-1">Impact</p>
                      <p className="text-xl font-bold text-white">₹1.2L</p>
                    </div>
                  </div>
                </div>
                <div className="pt-4 border-t border-slate-700 space-y-2">
                  <div className="flex items-center justify-between text-[10px] font-bold text-slate-500 uppercase tracking-widest">
                    <span>Reasoning Log</span>
                    <ChevronRight className="w-3 h-3" />
                  </div>
                  <div className="text-[11px] font-mono text-slate-400 space-y-1">
                    <p>&gt; Analyzing failure: INSUFFICIENT_FUNDS</p>
                    <p>&gt; Historical success on Friday AM: High</p>
                    <p>&gt; Policy check: PASSED</p>
                    <p>&gt; Strategy selected: RETRY_PAYMENT</p>
                  </div>
                </div>
              </div>
            </div>
          </div>
        </section>

        {/* CTA Section */}
        <section className="container mx-auto px-6 py-24">
          <div className="bg-slate-50 rounded-[2rem] p-12 md:p-20 text-center space-y-8 relative overflow-hidden">
            <div className="absolute top-0 left-0 w-full h-full bg-[radial-gradient(circle_at_top,_var(--tw-gradient-stops))] from-white/20 to-transparent" />
            <div className="max-w-2xl mx-auto space-y-6 relative z-10">
              <h2 className="text-4xl md:text-5xl font-bold tracking-tight">Stop losing revenue to failed payments.</h2>
              <p className="text-xl text-slate-600 leading-relaxed">
                Join high-growth businesses using RevFlow to optimize their billing performance and improve customer retention.
              </p>
              <div className="pt-6">
                <Link href="/login">
                  <Button size="lg" className="h-14 px-10 rounded-xl">
                    Get Started Now
                  </Button>
                </Link>
              </div>
            </div>
          </div>
        </section>
      </main>

      <footer className="border-t border-slate-100 py-12 bg-white">
        <div className="container mx-auto px-6">
          <div className="flex flex-col md:flex-row justify-between items-center gap-8">
            <div className="flex items-center gap-2">
              <div className="w-6 h-6 bg-slate-900 rounded flex items-center justify-center">
                <RefreshCcw className="w-3.5 h-3.5 text-white" />
              </div>
                  <span className="font-display font-bold text-lg tracking-tight">RevFlow</span>
            </div>
            <p className="text-sm text-slate-400 font-medium">
              &copy; {new Date().getFullYear()} RevFlow. All rights reserved.
            </p>
            <div className="flex items-center gap-6">
              <Link href="#" className="text-xs font-bold text-slate-400 hover:text-slate-900 uppercase tracking-widest transition-colors">Privacy</Link>
              <Link href="#" className="text-xs font-bold text-slate-400 hover:text-slate-900 uppercase tracking-widest transition-colors">Terms</Link>
            </div>
          </div>
        </div>
      </footer>
    </div>
  );
}
