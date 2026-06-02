import { useSyncExternalStore } from 'react';

const emptySubscribe = () => () => {};

/**
 * Returns `false` during SSR and the initial hydration render, then `true`.
 *
 * Hydration-safe replacement for the `useState(false)` + `useEffect(() =>
 * setMounted(true))` flag: it reads a server snapshot (`false`) and a client
 * snapshot (`true`) instead of synchronously setting state inside an effect,
 * which the React Compiler / react-hooks lint flags as a cascading-render risk.
 */
export function useMounted(): boolean {
  return useSyncExternalStore(
    emptySubscribe,
    () => true,
    () => false,
  );
}
