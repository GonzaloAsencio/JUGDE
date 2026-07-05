'use client';

import { useEffect, useState } from 'react';
import { Loader2 } from 'lucide-react';
import type { ApiError } from '@/lib/types';

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
    case 'rate_limit':
      return {
        headline: 'Too many requests.',
        detail: error.retryAfter != null
          ? 'Please wait before consulting the judge again.'
          : 'You are asking faster than the judge can rule. Please wait a moment.',
        retryable: true,
      };
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

  // Rate-limit countdown: block the retry until the server's window elapses.
  const [remaining, setRemaining] = useState(
    error.type === 'rate_limit' ? error.retryAfter ?? 0 : 0
  );
  useEffect(() => {
    if (remaining <= 0) return;
    const t = setInterval(() => setRemaining((s) => Math.max(0, s - 1)), 1000);
    return () => clearInterval(t);
  }, [remaining]);

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

        {retryable && (
          <button
            type="button"
            onClick={onRetry}
            disabled={waiting || retrying}
            className="mt-5 inline-flex items-center gap-2 text-[11px] font-bold uppercase tracking-[0.18em] text-brand-accent underline-offset-4 transition-colors hover:underline disabled:cursor-not-allowed disabled:text-brand-ink-faint disabled:no-underline"
          >
            {retrying && <Loader2 className="size-3 animate-spin" />}
            {retrying ? 'Retrying' : waiting ? `Try again in ${remaining}s` : 'Try again'}
          </button>
        )}
      </div>
    </div>
  );
}
