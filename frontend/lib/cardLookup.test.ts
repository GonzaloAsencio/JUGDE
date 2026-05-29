jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'yasuo windrider',
      image_url: 'https://example.com/yasuo.png',
      set_label: 'Origins',
      riftbound_id: 'ori-042-219',
    },
    {
      clean_name: 'atakhan',
      image_url: 'https://example.com/atakhan.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-170-219',
    },
  ],
}));

import { lookupCard } from '@/lib/cardLookup';

describe('lookupCard', () => {
  it('returns the entry for an exact lowercase match', () => {
    const card = lookupCard('yasuo windrider');
    expect(card?.riftbound_id).toBe('ori-042-219');
  });

  it('is case-insensitive', () => {
    const card = lookupCard('YASUO WINDRIDER');
    expect(card?.clean_name).toBe('yasuo windrider');
  });

  it('trims surrounding whitespace', () => {
    const card = lookupCard('  Atakhan  ');
    expect(card?.riftbound_id).toBe('unl-170-219');
  });

  it('returns undefined for a name not in the index', () => {
    expect(lookupCard('QwertyZorbax')).toBeUndefined();
  });

  it('returns undefined for empty string', () => {
    expect(lookupCard('')).toBeUndefined();
  });

  it('handles mixed-case query against lowercase index entry', () => {
    const card = lookupCard('AtAkHaN');
    expect(card?.clean_name).toBe('atakhan');
  });
});
