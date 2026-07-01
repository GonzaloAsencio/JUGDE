import { confidenceLevel } from '@/lib/confidence';

describe('confidenceLevel', () => {
  it('returns null for null/undefined', () => {
    expect(confidenceLevel(null)).toBeNull();
    expect(confidenceLevel(undefined)).toBeNull();
  });
  it('returns high when score >= 0.75', () => expect(confidenceLevel(0.9)).toBe('high'));
  it('returns medium when score is between 0.55 and 0.75', () =>
    expect(confidenceLevel(0.65)).toBe('medium'));
  it('returns low when score < 0.55', () => expect(confidenceLevel(0.4)).toBe('low'));
  it('boundary: 0.75 exactly is high', () => expect(confidenceLevel(0.75)).toBe('high'));
  it('boundary: 0.55 exactly is medium', () => expect(confidenceLevel(0.55)).toBe('medium'));
  it('exact card match score 1.0 is high', () => expect(confidenceLevel(1.0)).toBe('high'));
});
