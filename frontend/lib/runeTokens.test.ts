import { detectRuneTokens, resolveRuneToken } from './runeTokens';

describe('resolveRuneToken', () => {
  it('resolves might / exhaust / rainbow to their SVGs', () => {
    expect(resolveRuneToken('might')).toMatchObject({ kind: 'img', src: '/rb_might.svg', alt: 'Might', emphasis: true });
    expect(resolveRuneToken('exhaust')).toMatchObject({ kind: 'img', src: '/rb_exhaust.svg', alt: 'Exhaust' });
    expect(resolveRuneToken('rune_rainbow')).toMatchObject({ kind: 'img', src: '/rb_rune_rainbow.svg', alt: 'Any rune' });
  });

  it('every resolved token carries a non-empty description', () => {
    for (const t of ['might', 'exhaust', 'rune_rainbow', 'rune_fury', 'energy_2']) {
      expect(resolveRuneToken(t)?.desc).toEqual(expect.any(String));
      expect(resolveRuneToken(t)?.desc.length).toBeGreaterThan(0);
    }
  });

  it('resolves a colored rune to its bare SVG', () => {
    expect(resolveRuneToken('rune_fury')).toMatchObject({ kind: 'img', src: '/fury.svg', alt: 'Fury rune' });
  });

  it('resolves energy_N to an energy descriptor', () => {
    expect(resolveRuneToken('energy_3')).toMatchObject({ kind: 'energy', value: 3, alt: '3 energy' });
  });

  it('returns undefined for tokens outside the whitelist', () => {
    expect(resolveRuneToken('kwargs')).toBeUndefined();
    expect(resolveRuneToken('energy_9')).toBeUndefined();
    expect(resolveRuneToken('rune_purple')).toBeUndefined();
  });
});

describe('detectRuneTokens', () => {
  it('returns a single plain segment when no token present', () => {
    expect(detectRuneTokens('deal damage')).toEqual([{ text: 'deal damage' }]);
  });

  it('returns empty-string segment unchanged', () => {
    expect(detectRuneTokens('')).toEqual([{ text: '' }]);
  });

  it('splits out a known token and keeps surrounding text', () => {
    const segs = detectRuneTokens('pay :rb_energy_1: to act');
    expect(segs[0]).toEqual({ text: 'pay ' });
    expect(segs[1].text).toBe(':rb_energy_1:');
    expect(segs[1].token).toMatchObject({ kind: 'energy', value: 1, alt: '1 energy' });
    expect(segs[2]).toEqual({ text: ' to act' });
  });

  it('detects multiple tokens in one string', () => {
    const segs = detectRuneTokens(':rb_might: and :rb_rune_fury:');
    const tokens = segs.filter(s => s.token);
    expect(tokens).toHaveLength(2);
    expect(tokens[0].token).toMatchObject({ src: '/rb_might.svg' });
    expect(tokens[1].token).toMatchObject({ src: '/fury.svg' });
  });

  it('does NOT match noise tokens like :rb_kwargs:', () => {
    const segs = detectRuneTokens('debug :rb_kwargs: trace');
    expect(segs).toEqual([{ text: 'debug :rb_kwargs: trace' }]);
  });
});
