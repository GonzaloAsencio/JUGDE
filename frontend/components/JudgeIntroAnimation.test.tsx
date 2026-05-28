import { render, screen, act } from '@testing-library/react';
import { JudgeIntroAnimation } from './JudgeIntroAnimation';

describe('JudgeIntroAnimation', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  it('renders JUDGE! text', () => {
    render(<JudgeIntroAnimation onComplete={jest.fn()} />);
    const elements = screen.getAllByText('JUDGE!');
    expect(elements.length).toBeGreaterThanOrEqual(1);
  });

  it('does not call onComplete before animation ends', () => {
    const onComplete = jest.fn();
    render(<JudgeIntroAnimation onComplete={onComplete} />);
    act(() => { jest.advanceTimersByTime(1000); });
    expect(onComplete).not.toHaveBeenCalled();
  });

  it('calls onComplete after 1800ms', () => {
    const onComplete = jest.fn();
    render(<JudgeIntroAnimation onComplete={onComplete} />);
    act(() => { jest.advanceTimersByTime(1800); });
    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it('renders as a fixed overlay', () => {
    const { container } = render(<JudgeIntroAnimation onComplete={jest.fn()} />);
    const overlay = container.firstChild as HTMLElement;
    expect(overlay).toHaveClass('fixed');
  });
});
