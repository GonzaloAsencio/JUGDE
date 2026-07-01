import type { ConfidenceLevel } from './types';

// Map the backend's confidence score (0..1) to a display level. The backend is
// the single source of truth: it already excludes the 0.0 lexical similarity of
// tag/card matches and treats an exact card detection as maximal. Averaging the
// raw citation similarities here (the old approach) wrongly dragged card lookups
// to "low" because detected cards carry similarity 0.0.
export function confidenceLevel(score: number | null | undefined): ConfidenceLevel | null {
  if (score == null) return null;
  if (score >= 0.75) return 'high';
  if (score >= 0.55) return 'medium';
  return 'low';
}
