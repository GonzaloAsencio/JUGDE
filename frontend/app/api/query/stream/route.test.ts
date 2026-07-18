/**
 * @jest-environment node
 *
 * Tests for the /api/query/stream proxy route: it must PIPE the upstream SSE
 * body through without buffering (a buffered proxy turns streaming back into
 * one big flush — the exact UX this feature kills), forward the same auth/IP
 * headers as /api/query, and map pre-stream upstream errors to the same JSON
 * responses.
 */

const ORIGINAL_ENV = process.env;

const SSE_BODY =
  'event: token\ndata: {"text":"Hel"}\n\n' +
  'event: token\ndata: {"text":"lo"}\n\n' +
  'event: final\ndata: {"answer":"Hello","citations":[],"confidence":0.9,"cache_hit":false,"latency_ms":10}\n\n';

function makeRequest(body: unknown, headers: Record<string, string> = {}) {
  return new Request('http://localhost/api/query/stream', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', ...headers },
    body: JSON.stringify(body),
  });
}

function sseUpstream(body: string = SSE_BODY) {
  return jest.fn().mockResolvedValue(
    new Response(body, {
      status: 200,
      headers: { 'Content-Type': 'text/event-stream; charset=utf-8' },
    }),
  );
}

function jsonUpstream(status: number, body: unknown) {
  return jest.fn().mockResolvedValue(
    new Response(JSON.stringify(body), {
      status,
      headers: { 'Content-Type': 'application/json' },
    }),
  );
}

describe('POST /api/query/stream proxy', () => {
  beforeEach(() => {
    jest.resetModules();
    process.env = { ...ORIGINAL_ENV, PROXY_SHARED_SECRET: 'test-secret' };
  });

  afterEach(() => {
    process.env = ORIGINAL_ENV;
    jest.restoreAllMocks();
  });

  async function postViaRoute(
    headers: Record<string, string> = {},
    upstream: jest.Mock = sseUpstream(),
    body: unknown = { question: 'Can a unit attack twice?' },
  ) {
    global.fetch = upstream as unknown as typeof fetch;
    const { POST } = await import('./route');
    const res = await POST(makeRequest(body, headers) as never);
    return { res, upstream };
  }

  it('pipes the upstream SSE body through with text/event-stream', async () => {
    const { res } = await postViaRoute();

    expect(res.status).toBe(200);
    expect(res.headers.get('content-type')).toContain('text/event-stream');
    expect(await res.text()).toBe(SSE_BODY);
  });

  it('streams the BODY OBJECT through, not a buffered copy', async () => {
    // The route must hand the upstream ReadableStream to the Response —
    // res.body being a stream (not consumed/re-serialized) is what lets
    // events reach the browser as they arrive.
    const { res } = await postViaRoute();
    expect(res.body).toBeInstanceOf(ReadableStream);
  });

  it('targets the backend /query/stream endpoint', async () => {
    const { upstream } = await postViaRoute();

    const [url] = upstream.mock.calls[0];
    expect(String(url)).toContain('/api/v1/query/stream');
  });

  it('forwards X-Proxy-Secret and X-Real-IP like /api/query', async () => {
    const { upstream } = await postViaRoute({ 'x-forwarded-for': '203.0.113.7, 10.0.0.1' });

    const [, init] = upstream.mock.calls[0];
    expect(init.headers['X-Proxy-Secret']).toBe('test-secret');
    expect(init.headers['X-Real-IP']).toBe('203.0.113.7');
  });

  it('rejects a missing question with 400 before hitting the backend', async () => {
    const upstream = sseUpstream();
    const { res } = await postViaRoute({}, upstream, { not_a_question: true });

    expect(res.status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });

  it('maps upstream 429 through with Retry-After', async () => {
    const upstream = jsonUpstream(429, { detail: 'Rate limit exceeded.' });
    upstream.mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Rate limit exceeded.' }), {
        status: 429,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '30' },
      }),
    );
    const { res } = await postViaRoute({}, upstream);

    expect(res.status).toBe(429);
    expect(res.headers.get('Retry-After')).toBe('30');
  });

  it('maps upstream 401 to a generic 503 without leaking the auth detail', async () => {
    const { res } = await postViaRoute({}, jsonUpstream(401, { detail: 'Unauthorized' }));

    expect(res.status).toBe(503);
    const body = await res.json();
    expect(body.detail).not.toMatch(/unauthorized/i);
  });
});
