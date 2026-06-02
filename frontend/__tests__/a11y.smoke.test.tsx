// Accessibility smoke suite — Capa 0 safety net for the WCAG 2.1 AA work.
//
// jest-axe runs axe-core inside jsdom. Note: layout-dependent rules
// (color-contrast) cannot run here and are reported as "incomplete", not
// violations — contrast is handled manually in Capa 1.
//
// The QueryInput case is intentionally `test.failing`: it documents the
// CURRENT a11y debt (the text input has no associated <label>, the mention
// dropdown lacks combobox/listbox roles). It stays GREEN today because the
// failure is expected. When Capa 1 fixes QueryInput, this test will start
// PASSING, which flips `test.failing` to a failure and signals us to drop the
// `.failing` and promote it to a permanent regression guard.

jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'yasuo windrider',
      image_url: 'https://example.com/yasuo.png',
      set_label: 'Origins',
      riftbound_id: 'ori-042-219',
    },
  ],
}));

import { render } from '@testing-library/react';
import { useState } from 'react';
import { axe } from 'jest-axe';
import { QueryInput } from '@/components/QueryInput';
import { KeywordBadge } from '@/components/KeywordBadge';
import { GAME_KEYWORDS } from '@/lib/gameKeywords';

function QueryInputHarness() {
  const [value, setValue] = useState('');
  return (
    <QueryInput value={value} onChange={setValue} onSubmit={() => {}} loading={false} placeholder="Ask the judge" />
  );
}

describe('a11y smoke', () => {
  it('KeywordBadge has no axe violations', async () => {
    const { container } = render(<KeywordBadge def={GAME_KEYWORDS[0]} />);
    expect(await axe(container)).toHaveNoViolations();
  });

  // Expected RED until Capa 1 adds the <label> + ARIA combobox roles.
  it.failing('QueryInput has no axe violations (Capa 1 target)', async () => {
    const { container } = render(<QueryInputHarness />);
    expect(await axe(container)).toHaveNoViolations();
  });
});
