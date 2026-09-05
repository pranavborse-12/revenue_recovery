'use client';

import * as React from 'react';
import { useRouter } from 'next/navigation';
import { ArrowRight, CheckCircle2, RefreshCcw, ShieldCheck, Sparkles } from 'lucide-react';
import { useAuth } from '@/components/auth/AuthProvider';
import { isFirebaseConfigured } from '@/lib/firebase';
import { Button } from '@/components/ui/Button';

export default function LoginPage() {
  const router = useRouter();
  const { user, loading, signInWithGoogle } = useAuth();
  const [error, setError] = React.useState<string | null>(null);
  const [isSigningIn, setIsSigningIn] = React.useState(false);

  React.useEffect(() => {
    router.prefetch('/dashboard');
    if (!loading && user && !isSigningIn) router.replace('/dashboard');
  }, [isSigningIn, loading, router, user]);

  async function handleGoogleSignIn() {
    setError(null);
    setIsSigningIn(true);
    try {
      await signInWithGoogle();
      router.replace('/dashboard');
    } catch (signInError) {
      setError(signInError instanceof Error ? signInError.message : 'Google sign-in failed. Please try again.');
    } finally {
      setIsSigningIn(false);
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden bg-[#f7f8fb] px-5 py-8 text-slate-900">
      <div className="pointer-events-none absolute inset-x-0 top-0 h-72 bg-gradient-to-b from-emerald-50/80 to-transparent" />
      <div className="relative w-full max-w-md">
        <div className="mb-8 flex items-center justify-center gap-2.5">
          <div className="flex h-9 w-9 items-center justify-center rounded-xl bg-slate-950 shadow-sm"><RefreshCcw className="h-5 w-5 text-white" /></div>
          <span className="font-display text-xl font-bold tracking-tight">Revenue</span>
        </div>
        <section className="rounded-3xl border border-slate-200/90 bg-white p-7 shadow-xl shadow-slate-200/50 sm:p-9">
          <div className="mb-8">
            <div className="mb-5 flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700"><ShieldCheck className="h-5 w-5" /></div>
            <p className="mb-2 text-xs font-bold uppercase tracking-[0.15em] text-emerald-600">Secure workspace</p>
            <h1 className="font-display text-3xl font-bold tracking-tight">Welcome back</h1>
            <p className="mt-2 text-sm leading-relaxed text-slate-500">Sign in to manage your recovery operations.</p>
          </div>

          <Button onClick={handleGoogleSignIn} disabled={loading || isSigningIn} variant="outline" className="h-12 w-full justify-center gap-3 rounded-xl border-slate-300 bg-white text-sm font-semibold text-slate-700 shadow-sm hover:bg-slate-50">
            <GoogleMark />
            {isSigningIn ? 'Signing you in…' : 'Sign in with Google'}
            {!isSigningIn && <ArrowRight className="h-4 w-4 text-slate-400" />}
          </Button>

          {!isFirebaseConfigured && <p className="mt-4 rounded-xl bg-amber-50 p-3 text-xs leading-relaxed text-amber-800">Google sign-in needs Firebase configuration in the frontend environment.</p>}
          {error && <p role="alert" className="mt-4 rounded-xl bg-red-50 p-3 text-xs leading-relaxed text-red-700">{error}</p>}

          <div className="mt-7 border-t border-slate-100 pt-5">
            <div className="flex items-center gap-2 text-xs text-slate-400"><Sparkles className="h-3.5 w-3.5 text-emerald-500" /> Fast, secure access to your recovery dashboard</div>
          </div>
        </section>
        <div className="mt-6 flex justify-center gap-5 text-xs text-slate-400">
          <span className="flex items-center gap-1.5"><CheckCircle2 className="h-3.5 w-3.5 text-emerald-500" /> Protected access</span>
          <span>Google authentication</span>
        </div>
      </div>
    </main>
  );
}

function GoogleMark() {
  return (
    <svg aria-hidden="true" className="h-5 w-5" viewBox="0 0 24 24">
      <path fill="#4285F4" d="M21.8 12.2c0-.7-.1-1.3-.2-1.9H12v3.6h5.5a4.7 4.7 0 0 1-2 3.1v2.4h3.2c1.9-1.8 3.1-4.4 3.1-7.2Z" />
      <path fill="#34A853" d="M12 22c2.7 0 5-.9 6.7-2.5l-3.2-2.4c-.9.6-2 .9-3.5.9-2.6 0-4.8-1.8-5.6-4.2H3.1v2.5A10 10 0 0 0 12 22Z" />
      <path fill="#FBBC05" d="M6.4 13.8A6 6 0 0 1 6.1 12c0-.6.1-1.2.3-1.8V7.7H3.1A10 10 0 0 0 3.1 16l3.3-2.2Z" />
      <path fill="#EA4335" d="M12 6a5.4 5.4 0 0 1 3.9 1.5l2.9-2.8A9.9 9.9 0 0 0 3.1 7.7l3.3 2.5C7.2 7.8 9.4 6 12 6Z" />
    </svg>
  );
}
