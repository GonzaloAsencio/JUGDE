import { deriveConfidence } from '@/lib/confidence';
import type { Citation } from '@/lib/types';

// deriveConfidence only reads `.similarity`; build full citations so the test
// stays typed against the real Citation contract (no `any`).
const cite = (similarity: number): Citation => ({
  section: '',
  source_type: '',
  content_preview: '',
  similarity,
});

describe('deriveConfidence', () => {
  it('returns null for empty array', () => expect(deriveConfidence([])).toBeNull());
  it('returns high when avg >= 0.75', () =>
    expect(deriveConfidence([cite(0.9), cite(0.85), cite(0.88)])).toBe('high'));
  it('returns medium when avg is between 0.55 and 0.75', () =>
    expect(deriveConfidence([cite(0.9), cite(0.5)])).toBe('medium'));
  it('returns low when avg < 0.55', () =>
    expect(deriveConfidence([cite(0.4), cite(0.5)])).toBe('low'));
  it('boundary: 0.75 exactly is high', () =>
    expect(deriveConfidence([cite(0.75)])).toBe('high'));
  it('boundary: 0.55 exactly is medium', () =>
    expect(deriveConfidence([cite(0.55)])).toBe('medium'));
});
