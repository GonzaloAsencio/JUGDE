/**
 * @jest-environment node
 *
 * /api/usage proxy: forwards identity to the backend meter, mints the anon
 * cookie on first visit, and degrades to 503 without throwing.
 */
export {}; // module scope: keep top-level test helpers out of the global namespace

const ORIGINAL_ENV = process.env;

function makeRequest(headers: Record<string, string> = {}) {
  return new Request('http://localhost/api/usage', { method: 'GET', headers });
}

function mockUpstream(status: number, body: unknown) {
  return jest.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }),
  );
}

describe('GET /api/usage proxy', () => {
  beforeEach(() => {
    jest.resetModules();
    process.env = { ...ORIGINAL_ENV, PROXY_SHARED_SECRET: 'test-secret', JUDGE_UID_SECRET: 'uid-secret' };
  });
  afterEach(() => {
    process.env = ORIGINAL_ENV;
    jest.restoreAllMocks();
  });

  async function getViaRoute(headers: Record<string, string> = {}, upstream = mockUpstream(200, { used: 100, quota: 20000, remaining: 19900, tier: 'anon', resets_at: 'x' })) {
    global.fetch = upstream as unknown as typeof fetch;
    const { GET } = await import('./route');
    const res = await GET(makeRequest(headers) as never);
    return { res, upstream };
  }

  it('forwards a minted X-User-Id and proxy secret to the backend meter', async () => {
    const { upstream } = await getViaRoute();

    const [url, init] = upstream.mock.calls[0];
    expect(url).toMatch(/\/api\/v1\/usage$/);
    expect(init.headers['X-Proxy-Secret']).toBe('test-secret');
    expect(init.headers['X-User-Id']).toMatch(/^anon:/);
  });

  it('sets the anon cookie on the first visit', async () => {
    const { res } = await getViaRoute();

    expect(res.headers.get('Set-Cookie')).toContain('judge_uid=');
  });

  it('returns the backend usage payload', async () => {
    const { res } = await getViaRoute();

    const body = await res.json();
    expect(body).toMatchObject({ used: 100, quota: 20000, remaining: 19900, tier: 'anon' });
  });

  it('degrades to 503 when the backend errors', async () => {
    const { res } = await getViaRoute({}, mockUpstream(500, { detail: 'boom' }));
    expect(res.status).toBe(503);
  });

  it('degrades to 503 when the fetch throws', async () => {
    global.fetch = jest.fn().mockRejectedValue(new Error('network')) as unknown as typeof fetch;
    const { GET } = await import('./route');
    const res = await GET(makeRequest() as never);
    expect(res.status).toBe(503);
  });
});
