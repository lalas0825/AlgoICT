/**
 * Server-side Supabase client helpers.
 *
 * - createClient(): for Server Components, Route Handlers, Server Actions
 * - Used by `proxy.ts` to read the current session from cookies
 *
 * Never import this from a client component.
 */

import { createServerClient, type CookieOptions } from '@supabase/ssr';
import { cookies } from 'next/headers';
import type { NextRequest, NextResponse } from 'next/server';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? 'http://localhost:54321';
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? 'placeholder';

/**
 * For use in Server Components / Route Handlers / Server Actions.
 * Reads cookies via the Next headers API.
 */
export async function createClient() {
  const cookieStore = await cookies();

  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return cookieStore.getAll();
      },
      setAll(cookiesToSet) {
        try {
          for (const { name, value, options } of cookiesToSet) {
            cookieStore.set(name, value, options);
          }
        } catch {
          // Called from a Server Component — Next silently swallows the
          // write. The middleware/proxy will refresh the cookie on the
          // next request, so this is safe to ignore.
        }
      },
    },
  });
}

/**
 * For use from proxy.ts — needs direct request/response access so the
 * session cookie can be refreshed inline.
 */
export function createProxyClient(request: NextRequest, response: NextResponse) {
  return createServerClient(supabaseUrl, supabaseAnonKey, {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        for (const { name, value, options } of cookiesToSet) {
          request.cookies.set(name, value);
          response.cookies.set({ name, value, ...(options as CookieOptions) });
        }
      },
    },
  });
}
