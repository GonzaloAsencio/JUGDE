jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'jhin virtuoso',
      image_url: 'https://example.com/jhin.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-181-219',
    },
    {
      clean_name: 'ashe focused',
      image_url: 'https://example.com/ashe.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-169-219',
    },
    {
      clean_name: 'ahri nine tailed fox',
      image_url: 'https://example.com/ahri.png',
      set_label: 'Origins',
      riftbound_id: 'ogn-001-219',
    },
    // single-word card — must NOT be detected in free text
    {
      clean_name: 'eclipse',
      image_url: 'https://example.com/eclipse.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-200-219',
    },
  ],
}));

import { detectCards } from '@/lib/cardDetection';

describe('detectCards', () => {
  it('returns a single plain segment when there is no card name', () => {
    const segments = detectCards('the unit deals two damage');
    expect(segments).toEqual([{ text: 'the unit deals two damage' }]);
  });

  it('detects a multi-word card name in free text', () => {
    const segments = detectCards('then Jhin Virtuoso deals 2 damage');
    const tagged = segments.filter(s => s.card);
    expect(tagged).toHaveLength(1);
    expect(tagged[0].card?.riftbound_id).toBe('unl-181-219');
    expect(tagged[0].text).toBe('Jhin Virtuoso');
  });

  it('preserves surrounding text around the match', () => {
    const segments = detectCards('then Jhin Virtuoso deals 2 damage');
    expect(segments.map(s => s.text).join('')).toBe('then Jhin Virtuoso deals 2 damage');
  });

  it('does NOT detect single-word card names (avoids false positives)', () => {
    const segments = detectCards('a solar eclipse darkens the sky');
    expect(segments.every(s => !s.card)).toBe(true);
  });

  it('detects several multi-word cards in the same text', () => {
    const segments = detectCards('Jhin Virtuoso and Ashe Focused enter play');
    const ids = segments.filter(s => s.card).map(s => s.card?.riftbound_id);
    expect(ids).toEqual(['unl-181-219', 'unl-169-219']);
  });

  it('is case-insensitive', () => {
    const segments = detectCards('JHIN VIRTUOSO triggers');
    expect(segments.some(s => s.card?.riftbound_id === 'unl-181-219')).toBe(true);
  });

  it('matches a display name with " - " and hyphenated words against the slug', () => {
    const segments = detectCards('The Ahri - Nine-Tailed Fox reduces Might');
    const tagged = segments.filter(s => s.card);
    expect(tagged).toHaveLength(1);
    expect(tagged[0].card?.riftbound_id).toBe('ogn-001-219');
    expect(tagged[0].text).toBe('Ahri - Nine-Tailed Fox');
  });

  it('returns a single plain segment for empty input', () => {
    expect(detectCards('')).toEqual([{ text: '' }]);
  });
});
