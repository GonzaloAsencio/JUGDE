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

  it('renders general game keywords as a dotted-underline tooltip trigger (no badge)', () => {
    render(
      <AnswerDisplay answer="The banish effect removes" loading={false} error={null} />
    );
    const el = screen.getByText('banish');
    // not a colored badge: no skewed background sibling
    expect(el.previousElementSibling).toBeNull();
    expect(el.className).toContain('underline');
  });

  it('strips the brackets around a bracketed keyword like [HIDDEN]', () => {
    render(
      <AnswerDisplay answer="hide a card with [HIDDEN] now" loading={false} error={null} />
    );
    expect(screen.getByText('HIDDEN')).toBeInTheDocument();
    // the literal "[" / "]" should not survive next to the badge
    expect(screen.queryByText(/\[\s*HIDDEN/)).toBeNull();
    expect(screen.queryByText(/HIDDEN\s*\]/)).toBeNull();
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

  it('renders a card chip for a backticked card name (inline code)', () => {
    render(
      <AnswerDisplay answer="You play `Jhin Virtuoso` on your turn" loading={false} error={null} />
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

  it('renders an icon for a known :rb_*: symbol token', () => {
    render(
      <AnswerDisplay answer="Pay to gain :rb_might: now" loading={false} error={null} />
    );
    const icon = screen.getByAltText('Might');
    expect(icon.tagName).toBe('IMG');
    expect(icon).toHaveAttribute('src', '/rb_might.svg');
  });

  it('renders a CSS circle for an energy token', () => {
    render(
      <AnswerDisplay answer="Costs :rb_energy_2: energy" loading={false} error={null} />
    );
    const el = screen.getByLabelText('2 energy');
    expect(el.tagName).toBe('SPAN');
    expect(el).toHaveTextContent('2');
  });

  it('leaves unknown :rb_*: noise as plain text', () => {
    render(
      <AnswerDisplay answer="trace :rb_kwargs: here" loading={false} error={null} />
    );
    expect(screen.queryByRole('img')).toBeNull();
    expect(screen.getByText(/:rb_kwargs:/)).toBeInTheDocument();
  });

  it('promotes a leading "Reasoning:" into a section eyebrow, not body text', () => {
    render(
      <AnswerDisplay answer={'Reasoning:\n\nThe rule applies here'} loading={false} error={null} />
    );
    const label = screen.getByText('reasoning');
    expect(label.tagName).toBe('SPAN');
    expect(label.className).toContain('uppercase');
    // the ":" should be consumed by the label, not leak into the body
    expect(screen.queryByText(/Reasoning:/)).toBeNull();
  });

  it('renders an "Answer:" eyebrow in the accent color and keeps the conclusion text', () => {
    render(
      <AnswerDisplay answer={'Answer: The card wins'} loading={false} error={null} />
    );
    const label = screen.getByText('answer');
    expect(label.className).toContain('text-brand-accent');
    expect(screen.getByText(/The card wins/)).toBeInTheDocument();
  });

  it('leaves an ordinary paragraph untouched when there is no section heading', () => {
    render(
      <AnswerDisplay answer="Just a plain sentence about the rules" loading={false} error={null} />
    );
    expect(screen.queryByText('answer')).toBeNull();
    expect(screen.queryByText('reasoning')).toBeNull();
    expect(screen.getByText(/Just a plain sentence/)).toBeInTheDocument();
  });

  it('renders three bouncing dots when loading', () => {
    const { container } = render(
      <AnswerDisplay answer={null} loading={true} error={null} />
    );
    const dots = container.querySelectorAll('.animate-bounce');
    expect(dots).toHaveLength(3);
  });
});
