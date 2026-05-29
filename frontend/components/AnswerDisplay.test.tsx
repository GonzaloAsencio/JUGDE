jest.mock('@/lib/cardIndex', () => ({
  CARD_INDEX: [
    {
      clean_name: 'jhin virtuoso',
      image_url: 'https://example.com/jhin.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-181-219',
    },
    {
      clean_name: 'eclipse',
      image_url: 'https://example.com/eclipse.png',
      set_label: 'Unleashed',
      riftbound_id: 'unl-200-219',
    },
  ],
}));

import { render, screen } from '@testing-library/react';
import { AnswerDisplay } from './AnswerDisplay';

describe('AnswerDisplay', () => {
  it('renders null when no answer, no loading, no error', () => {
    const { container } = render(
      <AnswerDisplay answer={null} loading={false} error={null} />
    );
    expect(container.firstChild).toBeNull();
  });

  it('renders skeleton when loading', () => {
    const { container } = render(
      <AnswerDisplay answer={null} loading={true} error={null} />
    );
    expect(container.firstChild).toBeTruthy();
  });

  it('renders a styled badge for a card keyword in the answer', () => {
    render(
      <AnswerDisplay answer="Use ACCELERATE to win" loading={false} error={null} />
    );
    const text = screen.getByText('ACCELERATE');
    expect(text.tagName).toBe('SPAN');
    const bg = text.previousElementSibling as HTMLElement;
    expect(bg).toHaveStyle({ backgroundColor: '#26705f' });
  });

  it('renders plain text for general game keywords', () => {
    render(
      <AnswerDisplay answer="The banish effect removes" loading={false} error={null} />
    );
    const el = screen.getByText(/banish/);
    expect(el.tagName).not.toBe('SPAN');
  });

  it('renders multiple badges in one answer', () => {
    render(
      <AnswerDisplay answer="ASSAULT and DEFLECT are different" loading={false} error={null} />
    );
    expect(screen.getByText('ASSAULT').previousElementSibling).toHaveStyle({ backgroundColor: '#bb2f65' });
    expect(screen.getByText('DEFLECT').previousElementSibling).toHaveStyle({ backgroundColor: '#93af34' });
  });

  it('renders a card chip for a multi-word card name in the answer', () => {
    render(
      <AnswerDisplay answer="Then Jhin Virtuoso deals damage" loading={false} error={null} />
    );
    expect(screen.getByText('JHIN VIRTUOSO')).toBeInTheDocument();
    expect(document.querySelector('[data-slot="hover-card-trigger"]')).not.toBeNull();
  });

  it('does not chip single-word card names in the answer', () => {
    render(
      <AnswerDisplay answer="A solar eclipse occurs at night" loading={false} error={null} />
    );
    expect(document.querySelector('[data-slot="hover-card-trigger"]')).toBeNull();
  });

  it('renders three bouncing dots when loading', () => {
    const { container } = render(
      <AnswerDisplay answer={null} loading={true} error={null} />
    );
    const dots = container.querySelectorAll('.animate-bounce');
    expect(dots).toHaveLength(3);
  });
});
