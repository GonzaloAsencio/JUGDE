// Capa 1 (a11y AA) — accessible-name + ARIA combobox contract for QueryInput.
// Written RED-first: these assertions fail against the pre-Capa-1 component.

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

import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { useState } from 'react';
import { QueryInput } from './QueryInput';

function Harness() {
  const [value, setValue] = useState('');
  return (
    <QueryInput value={value} onChange={setValue} onSubmit={() => {}} loading={false} placeholder="Ask the judge" />
  );
}

describe('QueryInput accessibility', () => {
  it('exposes the text field as a combobox with an accessible name', () => {
    render(<Harness />);
    const combobox = screen.getByRole('combobox', { name: /ask the judge/i });
    expect(combobox).toHaveAttribute('aria-expanded', 'false');
  });

  it('gives the submit control an accessible name', () => {
    render(<Harness />);
    expect(screen.getByRole('button', { name: /send|ask|submit/i })).toBeInTheDocument();
  });

  it('marks the suggestion list as a listbox with selectable options', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const combobox = screen.getByRole('combobox', { name: /ask the judge/i });
    await user.type(combobox, '#de');

    expect(combobox).toHaveAttribute('aria-expanded', 'true');
    const listbox = screen.getByRole('listbox');
    const options = within(listbox).getAllByRole('option');
    expect(options.length).toBeGreaterThan(0);
    expect(options[0]).toHaveAttribute('aria-selected', 'true');
    expect(combobox).toHaveAttribute('aria-activedescendant', options[0].id);
  });
});
