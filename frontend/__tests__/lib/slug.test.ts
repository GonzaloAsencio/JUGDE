jest.mock('@/content/sections.json', () => ({ 'Game Concepts': 'game-concepts', '101.': '101' }), {
  virtual: true,
});

import { sectionToSlug } from '@/lib/slug';

describe('sectionToSlug', () => {
  it('returns slug for known section', () => expect(sectionToSlug('Game Concepts')).toBe('game-concepts'));
  it('returns slug for numeric section', () => expect(sectionToSlug('101.')).toBe('101'));
  it('returns null for unknown section', () => expect(sectionToSlug('NonExistent')).toBeNull());
});
