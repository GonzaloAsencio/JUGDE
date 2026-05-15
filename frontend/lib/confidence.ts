import type { Citation, ConfidenceLevel } from './types';

export function deriveConfidence(citations: Citation[]): ConfidenceLevel | null {
  if (!citations.length) return null;
  const avg = citations.reduce((s, c) => s + c.similarity, 0) / citations.length;
  if (avg >= 0.75) return 'high';
  if (avg >= 0.55) return 'medium';
  return 'low';
}
