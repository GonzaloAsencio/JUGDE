import { act, renderHook } from '@testing-library/react';
import { useRevealedText } from './useRevealedText';

const LONG = 'Reasoning:\n- rule 820 applies to this case\n\nAnswer:\nYes, it repeats.';

describe('useRevealedText', () => {
  beforeEach(() => jest.useFakeTimers());
  afterEach(() => jest.useRealTimers());

  it('shows the initial value as-is (a loaded message must not replay its reveal)', () => {
    const { result } = renderHook(() => useRevealedText(LONG));
    expect(result.current).toBe(LONG);
  });

  it('animates text that lands at once (cache hit) instead of flashing it', () => {
    const { result, rerender } = renderHook(({ text }) => useRevealedText(text), {
      initialProps: { text: null as string | null },
    });

    rerender({ text: LONG });
    expect((result.current ?? '').length).toBeLessThan(LONG.length);

    act(() => jest.advanceTimersByTime(100));
    const partial = result.current ?? '';
    expect(partial.length).toBeGreaterThan(0);
    expect(partial.length).toBeLessThan(LONG.length);
    expect(LONG.startsWith(partial)).toBe(true);

    act(() => jest.advanceTimersByTime(2_000));
    expect(result.current).toBe(LONG);
  });

  it('drains within the bounded lag even for a large backlog', () => {
    const big = 'x'.repeat(5_000);
    const { result, rerender } = renderHook(({ text }) => useRevealedText(text), {
      initialProps: { text: null as string | null },
    });

    rerender({ text: big });
    act(() => jest.advanceTimersByTime(1_500));

    expect(result.current).toBe(big);
  });

  it('keeps animating as streaming deltas extend the text', () => {
    const { result, rerender } = renderHook(({ text }) => useRevealedText(text), {
      initialProps: { text: null as string | null },
    });

    rerender({ text: 'Hello ' });
    act(() => jest.advanceTimersByTime(2_000));
    expect(result.current).toBe('Hello ');

    rerender({ text: 'Hello world' });
    act(() => jest.advanceTimersByTime(2_000));
    expect(result.current).toBe('Hello world');
  });

  it('swaps instantly when the new text does not extend the displayed one (canonical final)', () => {
    const { result, rerender } = renderHook(({ text }) => useRevealedText(text), {
      initialProps: { text: 'streamed text [#1]' as string | null },
    });

    rerender({ text: 'streamed text' });
    expect(result.current).toBe('streamed text');
  });

  it('resets to null on restart', () => {
    const { result, rerender } = renderHook(({ text }) => useRevealedText(text), {
      initialProps: { text: 'partial answer' as string | null },
    });

    rerender({ text: null });
    expect(result.current).toBeNull();
  });
});
