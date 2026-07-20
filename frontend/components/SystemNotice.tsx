'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { ApiError } from '@/lib/types';

// A 429 has two shapes with opposite time horizons: the per-IP anti-flood
// backstop (seconds — "you're going too fast") and a daily quota/budget reset
// (hours — resets at midnight UTC). Above this threshold we stop the per-second
// countdown (a 6-hour ticking timer is noise) and show the reset clock time.
const SHORT_THROTTLE_MAX_S = 120;

interface SystemNoticeProps {
  error: ApiError;
  onRetry: () => void;
  /** True while a retry is in flight — keeps the notice up instead of the judge. */
  retrying?: boolean;
}

interface Copy {
  headline: string;
  detail: string;
  /** Validation is the user's input, not a transient fault — no point retrying. */
  retryable: boolean;
}

function copyFor(error: ApiError): Copy {
  switch (error.type) {
    case 'timeout':
      return { headline: 'The request timed out.', detail: 'The judge did not respond in time. Please try again.', retryable: true };
    case 'server':
      return { headline: 'The service is unavailable.', detail: 'Something went wrong on our side. Please try again in a moment.', retryable: true };
    case 'network':
      return { headline: 'Connection lost.', detail: 'We could not reach the service. Check your connection and try again.', retryable: true };
    case 'cold_start':
      return { headline: 'Waking up the judge…', detail: 'The service was asleep and is starting back up. This can take up to a minute — hang tight.', retryable: true };
    case 'rate_limit': {
      // A daily reset is not "too many requests" — it's a spent budget. The
      // backend already writes a case-specific, honest message (personal vs the
      // shared demo budget); surface it verbatim instead of generic throttle
      // copy that contradicts a badge still showing personal tokens left.
      const dailyReset = (error.retryAfter ?? 0) > SHORT_THROTTLE_MAX_S;
      const detail = error.message.trim()
        ? error.message
        : error.retryAfter != null
          ? 'Please wait before consulting the judge again.'
          : 'You are asking faster than the judge can rule. Please wait a moment.';
      return {
        headline: dailyReset ? 'Daily limit reached.' : 'Too many requests.',
        detail,
        retryable: true,
      };
    }
    case 'validation':
      return { headline: 'That question could not be processed.', detail: error.message, retryable: false };
    default:
      return { headline: 'Something went wrong.', detail: 'An unexpected error occurred. Please try again.', retryable: true };
  }
}

/**
 * A formal, system-level notice for request failures — deliberately NOT rendered
 * as a judge reply. Restrained brand palette, no icon, no alarm red: a ruling
 * engine reports a fault plainly, it doesn't panic.
 */
export function SystemNotice({ error, onRetry, retrying = false }: SystemNoticeProps) {
  const { headline, detail, retryable } = copyFor(error);

  const isDailyReset =
    error.type === 'rate_limit' && (error.retryAfter ?? 0) > SHORT_THROTTLE_MAX_S;

  // Daily reset: show the reopen moment in the viewer's local time ("midnight
  // UTC" is meaningless in another zone). Capture the clock ONCE in a lazy
  // initializer (Date.now() is impure — keep render pure) and derive the label
  // from that fixed instant.
  const [seenAt] = useState(() => Date.now());
  const resetLabel =
    isDailyReset && error.retryAfter != null
      ? new Date(seenAt + error.retryAfter * 1000).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        })
      : null;

  // Short-throttle countdown: block retry until the server's window elapses.
  // Skipped for a daily reset (a per-second timer over hours is noise). Re-init
  // when a fresh 429 changes the target via render-time adjustment (React's
  // documented pattern — no setState-in-effect cascade); one interval per
  // window, created on target change rather than per tick.
  const countdownFrom =
    error.type === 'rate_limit' && !isDailyReset ? error.retryAfter ?? 0 : 0;
  const [remaining, setRemaining] = useState(countdownFrom);
  const [countdownTarget, setCountdownTarget] = useState(countdownFrom);
  if (countdownTarget !== countdownFrom) {
    setCountdownTarget(countdownFrom);
    setRemaining(countdownFrom);
  }
  useEffect(() => {
    if (countdownFrom <= 0) return;
    const t = setInterval(() => {
      setRemaining((s) => {
        if (s <= 1) {
          clearInterval(t);
          return 0;
        }
        return s - 1;
      });
    }, 1000);
    return () => clearInterval(t);
  }, [countdownFrom]);

  const waiting = remaining > 0;

  return (
    <div className="flex justify-center py-2">
      <div
        role="alert"
        className="w-full max-w-md rounded-2xl border border-brand-ink/10 bg-brand-ink/[0.02] px-8 py-7 text-center"
      >
        <p className="text-[10px] font-bold uppercase tracking-[0.28em] text-brand-muted-ink">
          System Notice
        </p>
        <p className="mt-3 text-[15px] font-semibold text-brand-ink">{headline}</p>
        <p className="mx-auto mt-1.5 max-w-xs text-sm leading-relaxed text-brand-ink-soft">{detail}</p>

        {/* Daily reset: no retry affordance — the button would sit dead for
            hours. State when the meter reopens, in local time, and stop. */}
        {isDailyReset ? (
          <p className="mt-5 text-[11px] font-bold uppercase tracking-[0.18em] text-brand-muted-ink">
            Try again after {resetLabel}
          </p>
        ) : (
          retryable && (
            <button
              type="button"
              onClick={onRetry}
              disabled={waiting || retrying}
              className="mt-5 inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-brand-accent underline-offset-4 transition-colors hover:underline disabled:cursor-not-allowed disabled:text-brand-ink-faint disabled:no-underline"
            >
              {retrying && <Loader2 className="size-3 animate-spin" />}
              {retrying ? 'Retrying' : waiting ? `Try again in ${remaining}s` : 'Try again'}
            </button>
          )
        )}
      </div>
    </div>
  );
}
