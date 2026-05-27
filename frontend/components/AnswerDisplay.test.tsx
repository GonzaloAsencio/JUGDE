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
});
