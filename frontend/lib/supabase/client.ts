'use client';

import { createBrowserClient } from '@supabase/ssr';

/**
 * Browser-side Supabase client for the login button and session state. Reads
 * the public env vars (safe to expose — the anon key is designed for the
 * browser). Returns null when Supabase isn't configured, so the login UI
 * simply hides itself instead of crashing an un-configured deploy.
 */
export function createClient() {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return null;
  return createBrowserClient(url, anonKey);
}
