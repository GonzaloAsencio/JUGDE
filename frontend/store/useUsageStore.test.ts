import { useUsageStore } from './useUsageStore';

function mockFetch(payload: unknown, ok = true) {
  global.fetch = jest.fn().mockResolvedValue({
    ok,
    status: ok ? 200 : 503,
    json: async () => payload,
  }) as unknown as typeof fetch;
}

describe('useUsageStore.refresh', () => {
  beforeEach(() => useUsageStore.setState({ usage: null }));
  afterEach(() => jest.restoreAllMocks());

  it('adopts a well-formed meter payload', async () => {
    mockFetch({ used: 500, quota: 20000, remaining: 19500, resets_at: 'x', tier: 'anon' });

    await useUsageStore.getState().refresh();

    expect(useUsageStore.getState().usage).toMatchObject({ remaining: 19500, tier: 'anon' });
  });

  it('keeps the last value on a 503 (fail-open)', async () => {
    useUsageStore.setState({ usage: { used: 0, quota: 20000, remaining: 20000, resets_at: 'x', tier: 'anon' } });
    mockFetch({ detail: 'down' }, false);

    await useUsageStore.getState().refresh();

    expect(useUsageStore.getState().usage?.remaining).toBe(20000);
  });

  it('never throws on a network error', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('offline')) as unknown as typeof fetch;

    await expect(useUsageStore.getState().refresh()).resolves.toBeUndefined();
  });

  it('ignores a payload without the metering shape', async () => {
    mockFetch({ status: 'ok' });

    await useUsageStore.getState().refresh();

    expect(useUsageStore.getState().usage).toBeNull();
  });
});
