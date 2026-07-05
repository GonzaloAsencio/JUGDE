import { structureClauses, parseClause } from './structureClauses';

describe('structureClauses', () => {
  it('splits a run-on paragraph into one clause per paragraph', () => {
    const input = '133. Category 133.1. A card can have Categories. 133.2. They dictate behavior.';
    const out = structureClauses(input).split('\n\n');
    expect(out).toEqual([
      '133. Category',
      '133.1. A card can have Categories.',
      '133.2. They dictate behavior.',
    ]);
  });

  it('keeps cross-references ("See rule 428.") inline, not split as a clause', () => {
    const input = '141.1.b.4. Units can be Killed. See rule 428. Kill for more information.';
    const out = structureClauses(input);
    expect(out).toBe(input); // no split — the only number is a reference
    expect(out).not.toContain('\n\n428.');
  });

  it('breaks before an "Example:" note', () => {
    const input = '133.3. Effects can refer to types. Example: A "non-unit card" is not a unit.';
    const out = structureClauses(input).split('\n\n');
    expect(out).toContain('Example: A "non-unit card" is not a unit.');
    expect(out[0]).toBe('133.3. Effects can refer to types.');
  });

  it('leaves headings and prose without clause numbers untouched', () => {
    expect(structureClauses('# 100. Game Concepts')).toBe('# 100. Game Concepts');
    expect(structureClauses('Just a plain sentence.')).toBe('Just a plain sentence.');
  });

  it('parseClause reports the number and nesting depth', () => {
    expect(parseClause('133. Category')).toEqual({ num: '133', depth: 1, rest: 'Category' });
    expect(parseClause('133.4.a. Permanents')).toEqual({ num: '133.4.a', depth: 3, rest: 'Permanents' });
    expect(parseClause('135.2.e.5.a. text here')).toEqual({ num: '135.2.e.5.a', depth: 5, rest: 'text here' });
    expect(parseClause('plain text')).toBeNull();
  });
});
