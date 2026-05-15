import { deriveConfidence } from '@/lib/confidence';

describe('deriveConfidence', () => {
  it('returns null for empty array', () => expect(deriveConfidence([])).toBeNull());
  it('returns high when avg >= 0.75', () =>
    expect(deriveConfidence([{ similarity: 0.9 }, { similarity: 0.85 }, { similarity: 0.88 }] as any)).toBe('high'));
  it('returns medium when avg is between 0.55 and 0.75', () =>
    expect(deriveConfidence([{ similarity: 0.9 }, { similarity: 0.5 }] as any)).toBe('medium'));
  it('returns low when avg < 0.55', () =>
    expect(deriveConfidence([{ similarity: 0.4 }, { similarity: 0.5 }] as any)).toBe('low'));
  it('boundary: 0.75 exactly is high', () =>
    expect(deriveConfidence([{ similarity: 0.75 }] as any)).toBe('high'));
  it('boundary: 0.55 exactly is medium', () =>
    expect(deriveConfidence([{ similarity: 0.55 }] as any)).toBe('medium'));
});
