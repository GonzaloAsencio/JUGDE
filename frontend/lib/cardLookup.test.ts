jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'yasuo windrider',
      image_url: 'https://example.com/yasuo.png',
      set_label: 'Origins',
      riftbound_id: 'ori-042-219',
    },
    {
      clean_name: 'yasuo unforgiven',
      image_url: 'https://example.com/yasuo2.png',
      set_label: 'Origins',
      riftbound_id: 'ori-043-219',
    },
    {
      clean_name: 'atakhan',
      image_url: 'https://example.com/atakhan.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-170-219',
    },
    {
      clean_name: 'jhin virtuoso',
      image_url: 'https://example.com/jhin.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-181-219',
    },
  ],
}));

import { lookupCard, searchCards, toSlug } from '@/lib/cardLookup';

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

  it('resolves a hyphenated slug to its multi-word card', () => {
    const card = lookupCard('jhin-virtuoso');
    expect(card?.riftbound_id).toBe('unl-181-219');
  });

  it('resolves a bare prefix to the first matching card (first-wins)', () => {
    const card = lookupCard('jhin');
    expect(card?.clean_name).toBe('jhin virtuoso');
  });

  it('prefix match returns the first index entry when several share the prefix', () => {
    const card = lookupCard('yasuo');
    expect(card?.riftbound_id).toBe('ori-042-219');
  });
});

describe('toSlug', () => {
  it('lowercases and joins words with hyphens', () => {
    expect(toSlug('Jhin Virtuoso')).toBe('jhin-virtuoso');
  });

  it('collapses repeated whitespace', () => {
    expect(toSlug('  Yasuo   Windrider  ')).toBe('yasuo-windrider');
  });
});

describe('searchCards', () => {
  it('returns all cards whose name starts with the query, sorted alphabetically', () => {
    const results = searchCards('yasuo');
    // 'yasuo unforgiven' sorts before 'yasuo windrider'
    expect(results.map(c => c.riftbound_id)).toEqual(['ori-043-219', 'ori-042-219']);
  });

  it('sorts results alphabetically by clean_name regardless of index order', () => {
    const results = searchCards('ya');
    expect(results.map(c => c.clean_name)).toEqual(['yasuo unforgiven', 'yasuo windrider']);
  });

  it('is case-insensitive and trims', () => {
    const results = searchCards('  JH ');
    expect(results.map(c => c.clean_name)).toEqual(['jhin virtuoso']);
  });

  it('matches against the slug too', () => {
    const results = searchCards('jhin-vir');
    expect(results.map(c => c.clean_name)).toEqual(['jhin virtuoso']);
  });

  it('respects the limit', () => {
    const results = searchCards('', 2);
    expect(results).toHaveLength(2);
  });

  it('returns an empty array when nothing matches', () => {
    expect(searchCards('zzz')).toEqual([]);
  });
});
