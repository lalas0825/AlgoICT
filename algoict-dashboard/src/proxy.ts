/**
 * proxy.ts — Next.js 16 Proxy (formerly "middleware")
 *
 * Guards every page route behind a Supabase auth session. If no session
 * is present, requests are redirected to /login. The login page itself
 * and Next internals are excluded via the matcher.
 *
 * Session cookies are read+refreshed on every request via @supabase/ssr.
 */

import { NextResponse, type NextRequest } from 'next/server';
import { createProxyClient } from '@/shared/lib/supabase-server';

export async function proxy(request: NextRequest) {
  // Start from a plain "continue" response — the Supabase client may
  // mutate it by writing refreshed auth cookies on its way through.
  let response = NextResponse.next({
    request: { headers: request.headers },
  });

  const supabase = createProxyClient(request, response);

  // getUser() revalidates against Supabase (vs getSession() which only
  // reads the cookie). Required by @supabase/ssr to keep cookies fresh.
  const {
    data: { user },
  } = await supabase.auth.getUser();

  const { pathname } = request.nextUrl;

  // Authenticated users hitting /login jump straight to the dashboard
  if (user && pathname === '/login') {
    const url = request.nextUrl.clone();
    url.pathname = '/';
    return NextResponse.redirect(url);
  }

  // Unauthenticated users are bounced to /login for every guarded path
  if (!user && pathname !== '/login') {
    const url = request.nextUrl.clone();
    url.pathname = '/login';
    // Preserve intended destination as ?next=... for post-login redirect
    url.searchParams.set('next', pathname);
    return NextResponse.redirect(url);
  }

  return response;
}

// Skip Next internals, API routes, static assets, and the favicon.
// Every other route runs through the auth check above.
export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico|.*\\.(?:png|jpg|jpeg|svg|gif|webp)$).*)',
  ],
};
