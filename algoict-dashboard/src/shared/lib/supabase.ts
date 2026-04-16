/**
 * Browser-side Supabase client.
 *
 * Uses @supabase/ssr's createBrowserClient so that the auth session is
 * automatically kept in sync with the Next.js cookie store — the same
 * cookies the server-side proxy reads to protect routes.
 */

import { createBrowserClient } from '@supabase/ssr';

const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? 'http://localhost:54321';
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? 'placeholder';

export const supabase = createBrowserClient(supabaseUrl, supabaseAnonKey);
