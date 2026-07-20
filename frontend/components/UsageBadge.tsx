'use client';

import { useEffect } from 'react';
import { useUsageStore } from '@/store/useUsageStore';

const compact = new Intl.NumberFormat('en', { notation: 'compact', maximumFractionDigits: 1 });

// Local wall-clock reset time (the backend counts in UTC, but the reader cares
// about their own clock). Returns null on an unparseable timestamp.
function resetsClock(isoResetsAt: string): string | null {
  const when = new Date(isoResetsAt);
  if (Number.isNaN(when.getTime())) return null;
  return when.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' });
}

function resetsLabel(isoResetsAt: string): string {
  const time = resetsClock(isoResetsAt);
  return time ? `Resets at ${time}.` : 'Resets daily.';
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

  // Global budget spent: the personal remainder is still full but querying is
  // blocked, so showing "~20K left" contradicts the notice. State the block.
  if (usage.available === false) {
    const time = resetsClock(usage.resets_at);
    return (
      <p
        className="mt-2 text-center text-[11px] tracking-wide text-brand-ink-faint"
        title={resetsLabel(usage.resets_at)}
      >
        Demo limit reached{time ? ` · resets ${time}` : ''}
      </p>
    );
  }

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
