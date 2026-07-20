import { createServerClient } from '@supabase/ssr';
import { cookies } from 'next/headers';
import { NextRequest, NextResponse } from 'next/server';

/**
 * Sign out: clears the Supabase session cookies, dropping the user back to
 * anonymous metering (the anon cookie is minted again on the next query). POST
 * only — a GET would let a cross-site image tag log the user out.
 */
export async function POST(req: NextRequest) {
  const { origin } = new URL(req.url);
  const url = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY;

  if (url && anonKey) {
    const cookieStore = await cookies();
    const supabase = createServerClient(url, anonKey, {
      cookies: {
        getAll: () => cookieStore.getAll(),
        setAll: (list) => list.forEach(({ name, value, options }) => cookieStore.set(name, value, options)),
      },
    });
    await supabase.auth.signOut();
  }

  return NextResponse.redirect(`${origin}/`, { status: 303 });
}
