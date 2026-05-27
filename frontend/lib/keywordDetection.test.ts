import { detectKeywords } from './keywordDetection';

describe('detectKeywords', () => {
  it('returns a single plain segment when no keywords present', () => {
    expect(detectKeywords('hello world')).toEqual([{ text: 'hello world' }]);
  });

  it('returns empty-string segment unchanged', () => {
    expect(detectKeywords('')).toEqual([{ text: '' }]);
  });

  it('detects a card keyword case-insensitively', () => {
    const result = detectKeywords('use ACCELERATE to gain speed');
    expect(result).toEqual([
      { text: 'use ' },
      { text: 'ACCELERATE', keyword: expect.objectContaining({ name: 'accelerate', color: '#26705f' }) },
      { text: ' to gain speed' },
    ]);
  });

  it('detects lowercase card keyword', () => {
    const result = detectKeywords('use accelerate now');
    const kw = result.find(s => s.keyword);
    expect(kw?.keyword?.name).toBe('accelerate');
  });

  it('detects a plain-text game keyword with no color', () => {
    const result = detectKeywords('the banish effect');
    const seg = result.find(s => s.text.toLowerCase() === 'banish');
    expect(seg?.keyword).toBeDefined();
    expect(seg?.keyword?.color).toBeUndefined();
  });

  it('detects DEFLECT with black text color', () => {
    const result = detectKeywords('DEFLECT the blow');
    const kw = result.find(s => s.keyword)?.keyword;
    expect(kw?.name).toBe('deflect');
    expect(kw?.color).toBe('#93af34');
    expect(kw?.textColor).toBe('black');
  });

  it('handles hyphenated keyword quick-draw', () => {
    const result = detectKeywords('trigger quick-draw now');
    const kw = result.find(s => s.keyword)?.keyword;
    expect(kw?.name).toBe('quick-draw');
  });

  it('handles multi-word keyword "main phase"', () => {
    const result = detectKeywords('during main phase you act');
    const kw = result.find(s => s.keyword)?.keyword;
    expect(kw?.name).toBe('main phase');
  });

  it('detects multiple keywords in one string', () => {
    const result = detectKeywords('ASSAULT then DEFLECT');
    const keywords = result.filter(s => s.keyword);
    expect(keywords).toHaveLength(2);
    expect(keywords[0].keyword?.name).toBe('assault');
    expect(keywords[1].keyword?.name).toBe('deflect');
  });

  it('does not partially match inside longer words', () => {
    const result = detectKeywords('levelup');
    expect(result.every(s => !s.keyword)).toBe(true);
  });

  it('separates surrounding text correctly', () => {
    const result = detectKeywords('before STUN after');
    expect(result[0].text).toBe('before ');
    expect(result[2].text).toBe(' after');
  });
});
