'use client';

import { useEffect, useState } from 'react';
import { createClient } from '@/lib/supabase/client';

/**
 * Optional "Sign in with Google" control. Login is never required — it only
 * RAISES the daily token limit (anonymous users keep working). Renders nothing
 * when Supabase isn't configured, so an un-configured deploy shows no dead UI.
 */
export function AuthButton() {
  const [email, setEmail] = useState<string | null>(null);
  const [ready, setReady] = useState(false);
  // Memoize the client: createClient() reads env once and returns null when
  // Supabase is unconfigured — in which case this component renders nothing.
  const [supabase] = useState(() => createClient());

  useEffect(() => {
    if (!supabase) {
      setReady(true);
      return;
    }
    let active = true;
    supabase.auth.getUser().then(({ data }) => {
      if (active) {
        setEmail(data.user?.email ?? null);
        setReady(true);
      }
    });
    const { data: sub } = supabase.auth.onAuthStateChange((_event, session) => {
      setEmail(session?.user?.email ?? null);
    });
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, [supabase]);

  if (!supabase || !ready) return null;

  const signIn = () =>
    supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}/auth/callback` },
    });

  if (email) {
    return (
      <form action="/auth/signout" method="post" className="flex items-center gap-3">
        <span className="max-w-[12rem] truncate text-brand-ink-faint" title={email}>{email}</span>
        <button type="submit" className="hover:text-brand-accent transition-colors">
          Sign out
        </button>
      </form>
    );
  }

  return (
    <button type="button" onClick={signIn} className="hover:text-brand-accent transition-colors">
      Sign in with Google
    </button>
  );
}
