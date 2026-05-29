jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'atakhan',
      image_url: 'https://example.com/atakhan.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-170-219',
    },
  ],
}));

import { render, screen } from '@testing-library/react';
import { CardPreview } from '@/components/CardPreview';

describe('CardPreview', () => {
  it('renders children unwrapped when the card is not in the index', () => {
    render(
      <CardPreview cardName="nonexistent">
        <span data-testid="child">@nonexistent</span>
      </CardPreview>,
    );

    expect(screen.getByTestId('child')).toBeInTheDocument();
    // No trigger means base-ui's hover-card-trigger slot is absent.
    expect(document.querySelector('[data-slot="hover-card-trigger"]')).toBeNull();
  });

  it('wraps children in a HoverCardTrigger when the card exists', () => {
    render(
      <CardPreview cardName="Atakhan">
        <span data-testid="child">@Atakhan</span>
      </CardPreview>,
    );

    expect(screen.getByTestId('child')).toBeInTheDocument();
    const trigger = document.querySelector('[data-slot="hover-card-trigger"]');
    expect(trigger).not.toBeNull();
    expect(trigger?.contains(screen.getByTestId('child'))).toBe(true);
  });

  it('does not crash when cardName has surrounding whitespace', () => {
    render(
      <CardPreview cardName="  Atakhan  ">
        <span data-testid="child">trim</span>
      </CardPreview>,
    );

    // lookupCard trims internally, so trigger should still render
    expect(document.querySelector('[data-slot="hover-card-trigger"]')).not.toBeNull();
  });

  it('renders raw children when cardName is empty', () => {
    render(
      <CardPreview cardName="">
        <span data-testid="child">empty</span>
      </CardPreview>,
    );

    expect(screen.getByTestId('child')).toBeInTheDocument();
    expect(document.querySelector('[data-slot="hover-card-trigger"]')).toBeNull();
  });
});
