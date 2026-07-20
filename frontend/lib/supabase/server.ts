import { createServerClient } from '@supabase/ssr';
import type { NextRequest } from 'next/server';

/**
 * A Supabase server client scoped to a single route-handler request, used ONLY
 * to validate the session and read the authenticated user's id server-side.
 *
 * The cookie writer is intentionally a no-op: this client never refreshes or
 * mints auth cookies. Token refresh happens on the browser client and through
 * the /auth/callback exchange; here we only need to answer "is this request
 * carrying a valid session, and whose?". Trusting the client-sent id would let
 * anyone claim any auth:{sub} — getUser() re-validates the JWT with Supabase.
 *
 * Returns null (no client) when the public env vars are unset, so a deploy
 * without Supabase configured simply has no logged-in users — anonymous
 * metering keeps working untouched.
 */
export function createRequestClient(req: NextRequest) {
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;
  if (!url || !anonKey) return null;

  return createServerClient(url, anonKey, {
    cookies: {
      getAll: () => req.cookies.getAll().map(({ name, value }) => ({ name, value })),
      setAll: () => {
        // No-op: identity resolution must not mutate cookies. See the module
        // doc — refresh is owned by the browser client and the callback route.
      },
    },
  });
}

/**
 * The authenticated user's id ("auth:{sub}") when the request carries a valid
 * Supabase session, or null. Never throws — a network hiccup validating the
 * JWT must degrade to anonymous, never break a query.
 */
export async function getAuthUserId(req: NextRequest): Promise<string | null> {
  const supabase = createRequestClient(req);
  if (!supabase) return null;
  try {
    const { data, error } = await supabase.auth.getUser();
    if (error || !data.user) return null;
    return `auth:${data.user.id}`;
  } catch {
    return null;
  }
}
