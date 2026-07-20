import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';

/**
 * OAuth callback: Supabase redirects here with a `code` after the Google
 * consent screen. We exchange it for a session, which SETS the auth cookies on
 * the response — this is the one place identity cookies are minted, so it uses
 * a cookie-writing server client (unlike the read-only one in lib/supabase/server).
 */
export async function GET(req: NextRequest) {
  const { searchParams, origin } = new URL(req.url);
  const code = searchParams.get('code');
  const next = searchParams.get('next') ?? '/';

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (code && url && anonKey) {
    const cookieStore = await cookies();
    const supabase = createServerClient(url, anonKey, {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (list) => list.forEach(({ name, value, options }) => cookieStore.set(name, value, options)),
      },
    });
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error) return NextResponse.redirect(`${origin}${next}`);
  }

  // Any failure returns home with a flag — the UI shows a gentle notice rather
  // than a broken page; anonymous use continues regardless.
  return NextResponse.redirect(`${origin}/?auth_error=1`);
}
