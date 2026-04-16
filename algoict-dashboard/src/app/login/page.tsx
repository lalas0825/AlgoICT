'use client';

import { FormEvent, Suspense, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import OwlLogo from '@/shared/components/OwlLogo';
import { supabase } from '@/shared/lib/supabase';

export default function LoginPage() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-zinc-950" />}>
      <LoginForm />
    </Suspense>
  );
}

function LoginForm() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const nextPath = searchParams.get('next') ?? '/';

  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    setError(null);
    setSubmitting(true);

    const { error: signInError } = await supabase.auth.signInWithPassword({
      email: email.trim(),
      password,
    });

    if (signInError) {
      setError(signInError.message);
      setSubmitting(false);
      return;
    }

    // A full navigation ensures the proxy re-runs with the fresh cookie
    router.replace(nextPath.startsWith('/') ? nextPath : '/');
    router.refresh();
  };

  return (
    <div className="min-h-screen bg-zinc-950 flex items-center justify-center px-4">
      <div className="w-full max-w-sm">
        {/* Header / logo */}
        <div className="flex flex-col items-center mb-8">
          <OwlLogo size="lg" />
          <h1 className="mt-4 text-2xl font-bold text-zinc-50 tracking-tight">
            AlgoICT
          </h1>
          <p className="mt-1 text-xs text-zinc-500 uppercase tracking-wider">
            Sign in to continue
          </p>
        </div>

        {/* Form card */}
        <form
          onSubmit={onSubmit}
          className="bg-zinc-900 border border-zinc-800 rounded-xl p-6 flex flex-col gap-4"
        >
          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="email"
              className="text-[11px] text-zinc-500 uppercase tracking-wider font-medium"
            >
              Email
            </label>
            <input
              id="email"
              type="email"
              autoComplete="username"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              className="bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 transition"
              placeholder="you@example.com"
            />
          </div>

          <div className="flex flex-col gap-1.5">
            <label
              htmlFor="password"
              className="text-[11px] text-zinc-500 uppercase tracking-wider font-medium"
            >
              Password
            </label>
            <input
              id="password"
              type="password"
              autoComplete="current-password"
              required
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              className="bg-zinc-950 border border-zinc-800 rounded-md px-3 py-2 text-sm text-zinc-100 placeholder:text-zinc-600 focus:outline-none focus:border-zinc-600 transition"
              placeholder="••••••••"
            />
          </div>

          {error && (
            <div className="text-xs text-red-400 bg-red-500/10 border border-red-500/20 rounded-md px-3 py-2">
              {error}
            </div>
          )}

          <button
            type="submit"
            disabled={submitting || !email || !password}
            className="mt-2 bg-zinc-50 text-zinc-950 text-sm font-medium py-2 rounded-md hover:bg-zinc-200 transition disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {submitting ? 'Signing in…' : 'Sign in'}
          </button>
        </form>

        <div className="mt-4 text-center text-[11px] text-zinc-600 font-mono">
          READ-ONLY · SINGLE USER
        </div>
      </div>
    </div>
  );
}
