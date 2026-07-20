'use client';

import { useEffect } from 'react';
import { useUsageStore } from '@/store/useUsageStore';

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

function resetsLabel(isoResetsAt: string): string {
  const when = new Date(isoResetsAt);
  if (Number.isNaN(when.getTime())) return 'Resets daily.';
  // Local time so the tooltip is meaningful to the reader; the backend counts
  // in UTC but the wall-clock reset is what the user cares about.
  const time = when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
  return `Resets at ${time}.`;
}

/**
 * A discreet daily-token meter shown beside the input. Ambient by design: it
 * fetches on mount and re-reads after each answer (the query store triggers
 * the refresh), and renders nothing until it has a real number — a failed or
 * missing meter must never occupy space or raise alarm.
 */
export function UsageBadge() {
  const usage = useUsageStore((s) => s.usage);
  const refresh = useUsageStore((s) => s.refresh);

  useEffect(() => {
    void refresh();
  }, [refresh]);

  if (!usage) return null;

  const remaining = Math.max(usage.remaining, 0);
  return (
    <p
      className="mt-2 text-center text-[11px] tracking-wide text-brand-ink-faint"
      title={resetsLabel(usage.resets_at)}
    >
      ~{compact.format(remaining)} tokens left today
    </p>
  );
}
