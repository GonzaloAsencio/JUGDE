import { create } from 'zustand';
import type { UsageInfo } from '@/lib/types';

/**
 * The caller's daily token meter, kept separate from the query store: it is
 * ambient UI, so a fetch failure must never disturb the chat. The query store
 * calls `refresh()` after each completed answer, and the badge fetches once on
 * mount so it shows a real number before the first question.
 */
interface UsageState {
  usage: UsageInfo | null;
  refresh: () => Promise<void>;
}

export const useUsageStore = create<UsageState>((set) => ({
  usage: null,

  refresh: async () => {
    try {
      const res = await fetch('/api/usage');
      if (!res.ok) return; // 503 fail-open: leave the last known value, show nothing new
      const data = (await res.json()) as UsageInfo;
      // A backend without the metering fields (older deploy) must not render a
      // broken badge — require the shape before adopting it.
      if (typeof data?.remaining === 'number' && typeof data?.quota === 'number') {
        set({ usage: data });
      }
    } catch {
      // Network error: ambient meter stays as-is. Never throws into the caller.
    }
  },
}));
