/**
 * @jest-environment node
 *
 * Tests for the /api/query proxy route: forwarding of the shared secret and
 * the real client IP to the FastAPI backend, and error mapping.
 */

const ORIGINAL_ENV = process.env;

function makeRequest(body: unknown, headers: Record<string, string> = {}) {
  return new Request('http://localhost/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

function mockUpstream(status: number, body: unknown) {
  return jest.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

describe('POST /api/query proxy', () => {
  beforeEach(() => {
    jest.resetModules();
    process.env = { ...ORIGINAL_ENV, PROXY_SHARED_SECRET: 'test-secret' };
  });

  afterEach(() => {
    process.env = ORIGINAL_ENV;
    jest.restoreAllMocks();
  });

  async function postViaRoute(headers: Record<string, string> = {}, upstream = mockUpstream(200, { answer: 'ok' })) {
    global.fetch = upstream as unknown as typeof fetch;
    const { POST } = await import('./route');
    const res = await POST(makeRequest({ question: 'Can a unit attack twice?' }, headers) as never);
    return { res, upstream };
  }

  it('forwards X-Proxy-Secret from PROXY_SHARED_SECRET env', async () => {
    const { upstream } = await postViaRoute();

    const [, init] = upstream.mock.calls[0];
    expect(init.headers['X-Proxy-Secret']).toBe('test-secret');
  });

  it('forwards the first x-forwarded-for value as X-Real-IP', async () => {
    const { upstream } = await postViaRoute({ 'x-forwarded-for': '203.0.113.7, 10.0.0.1' });

    const [, init] = upstream.mock.calls[0];
    expect(init.headers['X-Real-IP']).toBe('203.0.113.7');
  });

  it('omits X-Real-IP when x-forwarded-for is absent', async () => {
    const { upstream } = await postViaRoute();

    const [, init] = upstream.mock.calls[0];
    expect(init.headers['X-Real-IP']).toBeUndefined();
  });

  it('omits X-Proxy-Secret when PROXY_SHARED_SECRET is unset', async () => {
    delete process.env.PROXY_SHARED_SECRET;
    const { upstream } = await postViaRoute();

    const [, init] = upstream.mock.calls[0];
    expect(init.headers['X-Proxy-Secret']).toBeUndefined();
  });

  it('maps upstream 401 to a generic 503 without leaking the auth detail', async () => {
    const { res } = await postViaRoute({}, mockUpstream(401, { detail: 'Unauthorized' }));

    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.detail).not.toMatch(/unauthorized/i);
  });

  it('still proxies a successful response', async () => {
    const { res } = await postViaRoute();

    expect(res.status).toBe(200);
    const body = await res.json();
    expect(body.answer).toBe('ok');
  });
});
