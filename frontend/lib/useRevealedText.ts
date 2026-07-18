'use client';

import { useEffect, useState } from 'react';

const TICK_MS = 33;
// The reveal may lag the real text by at most this much: the drain rate scales
// with the text length, so a fast producer (Cerebras bursts a whole answer in
// ~100ms; a cache hit delivers it all at once) still reads as a smooth stream
// instead of an instant wall of text — without ever adding more than ~1.2s.
const MAX_LAG_MS = 1200;
const MIN_CHARS_PER_TICK = 3;

function prefersReducedMotion(): boolean {
  return typeof window !== 'undefined'
    && typeof window.matchMedia === 'function'
    && window.matchMedia('(prefers-reduced-motion: reduce)').matches;
}

/**
 * Smoothly reveal *text* as it grows. The FIRST render shows the value as-is
 * (a fully loaded message must not replay its animation); afterwards:
 * - text extending the displayed value (streaming deltas, or a full answer
 *   landing at once) animates in at a length-proportional rate;
 * - text NOT extending it (the canonical final replacing streamed text, or a
 *   restart) swaps instantly;
 * - null resets.
 */
export function useRevealedText(text: string | null): string | null {
  const [displayed, setDisplayed] = useState<string | null>(text);
  const [prevText, setPrevText] = useState<string | null>(text);

  // Adjust-during-render (React's pattern for prop-driven state): instant
  // transitions happen synchronously here; only the animated drain needs the
  // effect below. No refs — the react-hooks rules (v6) forbid touching them
  // in render, and the effect never needs one.
  if (text !== prevText) {
    setPrevText(text);
    if (text === null || !text.startsWith(displayed ?? '') || prefersReducedMotion()) {
      setDisplayed(text);
    }
  }

  useEffect(() => {
    if (text === null) return;
    // The step is fixed PER TEXT CHANGE (length / tick budget): a
    // remaining-proportional step decays exponentially and never drains
    // inside the lag budget; a linear drain finishes on schedule. The updater
    // is functional so ticks compose correctly even when they fire faster
    // than React re-renders (fake timers, background tabs). The tick counter
    // makes the interval TERMINATE — without it every settled answer bubble
    // would keep a no-op interval ticking until unmount.
    const step = Math.max(MIN_CHARS_PER_TICK, Math.ceil(text.length / (MAX_LAG_MS / TICK_MS)));
    let ticksLeft = Math.ceil(text.length / step) + 1;
    const interval = setInterval(() => {
      if (ticksLeft-- <= 0) {
        clearInterval(interval);
        return;
      }
      setDisplayed(prev => {
        const shown = prev ?? '';
        // A stale tick after an instant swap/reset must never regress the text.
        if (!text.startsWith(shown) || shown.length >= text.length) return prev;
        return text.slice(0, shown.length + step);
      });
    }, TICK_MS);
    return () => clearInterval(interval);
  }, [text]);

  return displayed;
}
