import { render, screen, act } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { SystemNotice } from './SystemNotice';
import type { ApiError } from '@/lib/types';

const noop = () => {};

describe('SystemNotice', () => {
  it('labels itself a System Notice, never a judge reply', () => {
    render(<SystemNotice error={{ type: 'server', message: '' }} onRetry={noop} />);
    expect(screen.getByText('System Notice')).toBeInTheDocument();
    expect(screen.queryByText('Judge')).toBeNull();
  });

  it('shows tailored copy per error type', () => {
    const cases: Array<[ApiError['type'], RegExp]> = [
      ['timeout', /did not respond in time/i],
      ['server', /service is unavailable/i],
      ['network', /connection lost/i],
    ];
    for (const [type, re] of cases) {
      const { unmount } = render(<SystemNotice error={{ type, message: '' }} onRetry={noop} />);
      expect(screen.getByText(re)).toBeInTheDocument();
      unmount();
    }
  });

  it('calls onRetry when the retry action is pressed', async () => {
    const onRetry = jest.fn();
    const user = userEvent.setup();
    render(<SystemNotice error={{ type: 'timeout', message: '' }} onRetry={onRetry} />);
    await user.click(screen.getByRole('button', { name: /try again/i }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it('does not offer retry for a validation error (the input is the problem)', () => {
    render(<SystemNotice error={{ type: 'validation', message: 'Question is too long.' }} onRetry={noop} />);
    expect(screen.getByText('Question is too long.')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /try again/i })).toBeNull();
  });

  it('shows a disabled "Retrying" state while a retry is in flight', () => {
    render(<SystemNotice error={{ type: 'server', message: '' }} onRetry={noop} retrying />);
    const btn = screen.getByRole('button', { name: /retrying/i });
    expect(btn).toBeDisabled();
    expect(screen.queryByRole('button', { name: /^try again$/i })).toBeNull();
  });

  it('counts down and disables retry during a rate-limit window', () => {
    jest.useFakeTimers();
    try {
      render(<SystemNotice error={{ type: 'rate_limit', message: '', retryAfter: 3 }} onRetry={noop} />);
      const btn = screen.getByRole('button', { name: /try again in 3s/i });
      expect(btn).toBeDisabled();
      act(() => { jest.advanceTimersByTime(3000); });
      const ready = screen.getByRole('button', { name: /^try again$/i });
      expect(ready).toBeEnabled();
    } finally {
      jest.useRealTimers();
    }
  });
});
