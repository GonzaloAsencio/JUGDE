import { render, screen, waitFor, act } from '@testing-library/react';
import { UsageBadge } from './UsageBadge';
import { useUsageStore } from '@/store/useUsageStore';

function mockUsageFetch(payload: unknown, ok = true) {
  // jsdom has no global Response; a plain fetch-shaped stub is enough here.
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 503,
    json: async () => payload,
  }) as unknown as typeof fetch;
}

describe('UsageBadge', () => {
  beforeEach(() => {
    act(() => useUsageStore.setState({ usage: null }));
  });
  afterEach(() => jest.restoreAllMocks());

  it('renders nothing until a meter is available', () => {
    mockUsageFetch({}, false);
    const { container } = render(<UsageBadge />);
    expect(container).toBeEmptyDOMElement();
  });

  it('fetches on mount and shows the remaining tokens compactly', async () => {
    mockUsageFetch({ used: 1500, quota: 20000, remaining: 18500, resets_at: new Date().toISOString(), tier: 'anon' });

    render(<UsageBadge />);

    expect(await screen.findByText(/tokens left today/i)).toHaveTextContent(/18\.5K/i);
  });

  it('exposes the reset time as a tooltip', async () => {
    const resetsAt = new Date('2026-07-20T00:00:00Z').toISOString();
    mockUsageFetch({ used: 0, quota: 20000, remaining: 20000, resets_at: resetsAt, tier: 'anon' });

    render(<UsageBadge />);
    const badge = await screen.findByText(/tokens left today/i);

    expect(badge).toHaveAttribute('title', expect.stringMatching(/resets at/i));
  });

  it('renders nothing on a 503 (fail-open, no broken badge)', async () => {
    mockUsageFetch({ detail: 'usage unavailable' }, false);
    const { container } = render(<UsageBadge />);

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('ignores a payload missing the metering shape (older backend)', async () => {
    mockUsageFetch({ status: 'ok' }); // 200 but no remaining/quota
    const { container } = render(<UsageBadge />);

    await waitFor(() => expect(global.fetch).toHaveBeenCalled());
    expect(container).toBeEmptyDOMElement();
  });

  it('nudges anon users to sign in only when the balance is low', async () => {
    mockUsageFetch({ used: 17000, quota: 20000, remaining: 3000, resets_at: new Date().toISOString(), tier: 'anon' });
    render(<UsageBadge />);

    expect(await screen.findByText(/sign in to raise your limit/i)).toBeInTheDocument();
  });

  it('does not nudge a logged-in user', async () => {
    mockUsageFetch({ used: 99000, quota: 100000, remaining: 1000, resets_at: new Date().toISOString(), tier: 'auth' });
    render(<UsageBadge />);

    await screen.findByText(/tokens left today/i);
    expect(screen.queryByText(/sign in to raise/i)).toBeNull();
  });
});
