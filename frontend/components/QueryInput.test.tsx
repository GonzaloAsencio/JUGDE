jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'yasuo windrider',
      image_url: 'https://example.com/yasuo.png',
      set_label: 'Origins',
      riftbound_id: 'ori-042-219',
    },
    {
      clean_name: 'jhin virtuoso',
      image_url: 'https://example.com/jhin.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-181-219',
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
    <QueryInput
      value={value}
      onChange={setValue}
      onSubmit={() => {}}
      loading={false}
      placeholder="Ask"
    />
  );
}

describe('QueryInput mention picker', () => {
  it('shows keyword suggestions when typing the # sigil', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByPlaceholderText('Ask'), '#de');

    const dropdown = screen.getByTestId('mention-dropdown');
    expect(within(dropdown).getByText('DEFLECT')).toBeInTheDocument();
  });

  it('shows card suggestions with a thumbnail when typing the @ sigil', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByPlaceholderText('Ask'), '@ya');

    const dropdown = screen.getByTestId('mention-dropdown');
    expect(within(dropdown).getByText('yasuo windrider')).toBeInTheDocument();
    const img = within(dropdown).getByRole('img', { name: /yasuo windrider/i });
    expect(img).toHaveAttribute('src', 'https://example.com/yasuo.png');
  });

  it('does not show keyword results under the @ sigil', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByPlaceholderText('Ask'), '@de');
    // 'de' matches no card -> no dropdown, and certainly no DEFLECT keyword
    expect(screen.queryByText('DEFLECT')).toBeNull();
  });

  it('inserts the hyphenated slug when selecting a card', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByPlaceholderText('Ask') as HTMLInputElement;
    await user.type(input, '@ya');
    await user.click(screen.getByText('yasuo windrider'));

    expect(input.value).toBe('@yasuo-windrider ');
  });

  it('inserts the #keyword token when selecting a keyword', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const input = screen.getByPlaceholderText('Ask') as HTMLInputElement;
    await user.type(input, '#def');
    await user.click(screen.getByText('DEFLECT'));

    expect(input.value).toBe('#deflect ');
  });

  it('hides the dropdown when nothing matches', async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.type(screen.getByPlaceholderText('Ask'), '@zzzzz');
    expect(screen.queryByTestId('mention-dropdown')).toBeNull();
  });
});
