/**
 * @jest-environment node
 *
 * Tests for the SSE client: incremental frame parsing (frames arrive split
 * across arbitrary chunk boundaries), the token/restart/final handler
 * contract, and error mapping consistent with postQuery.
 */
import { ApiErrorInstance } from './api';
import { postQueryStream, sseEvents } from './streamQuery';

function streamOf(...chunks: string[]): ReadableStream<Uint8Array> {
  const encoder = new TextEncoder();
  return new ReadableStream({
    start(controller) {
      for (const chunk of chunks) controller.enqueue(encoder.encode(chunk));
      controller.close();
    },
  });
}

const FINAL_DATA = {
  answer: 'Hello',
  citations: [],
  confidence: 0.9,
  cache_hit: false,
  latency_ms: 10,
};

const SSE_BODY =
  'event: token\ndata: {"text":"Hel"}\n\n' +
  'event: token\ndata: {"text":"lo"}\n\n' +
  `event: final\ndata: ${JSON.stringify(FINAL_DATA)}\n\n`;

async function collect(body: ReadableStream<Uint8Array>) {
  const events = [];
  for await (const event of sseEvents(body)) events.push(event);
  return events;
}

describe('sseEvents', () => {
  it('parses events arriving as one chunk', async () => {
    const events = await collect(streamOf(SSE_BODY));

    expect(events.map(e => e.event)).toEqual(['token', 'token', 'final']);
    expect(events[0].data).toEqual({ text: 'Hel' });
    expect(events[2].data).toEqual(FINAL_DATA);
  });

  it('parses frames split across arbitrary chunk boundaries', async () => {
    // Split mid-"event:", mid-JSON, and mid-delimiter — the three seams a
    // network chunk boundary can actually hit.
    const events = await collect(streamOf(
      'event: tok',
      'en\ndata: {"te',
      'xt":"Hel"}\n',
      '\nevent: token\ndata: {"text":"lo"}\n\n',
      `event: final\ndata: ${JSON.stringify(FINAL_DATA)}\n\n`,
    ));

    expect(events.map(e => e.event)).toEqual(['token', 'token', 'final']);
    expect(events[0].data).toEqual({ text: 'Hel' });
  });
});

describe('postQueryStream', () => {
  afterEach(() => jest.restoreAllMocks());

  function mockFetch(body: string | ReadableStream<Uint8Array>, init: ResponseInit = {}) {
    const stream = typeof body === 'string' ? streamOf(body) : body;
    global.fetch = jest.fn().mockResolvedValue(
      new Response(stream, {
        status: 200,
        headers: { 'Content-Type': 'text/event-stream' },
        ...init,
      }),
    ) as unknown as typeof fetch;
  }

  function handlers() {
    return { onToken: jest.fn(), onRestart: jest.fn() };
  }

  it('delivers tokens then resolves with the final response', async () => {
    mockFetch(SSE_BODY);
    const h = handlers();

    const final = await postQueryStream('a question', [], h);

    expect(h.onToken.mock.calls.map(([t]) => t)).toEqual(['Hel', 'lo']);
    expect(final.answer).toBe('Hello');
    expect(final.cache_hit).toBe(false);
  });

  it('signals restart so the caller clears its partial answer', async () => {
    mockFetch(
      'event: token\ndata: {"text":"partial"}\n\n' +
      'event: restart\ndata: {}\n\n' +
      `event: final\ndata: ${JSON.stringify(FINAL_DATA)}\n\n`,
    );
    const h = handlers();

    await postQueryStream('a question', [], h);

    expect(h.onRestart).toHaveBeenCalledTimes(1);
  });

  it('maps a terminal error event with timeout detail to a timeout ApiError', async () => {
    mockFetch('event: error\ndata: {"detail":"Generation timeout"}\n\n');

    await expect(postQueryStream('a question', [], handlers())).rejects.toMatchObject({
      name: 'ApiError',
      type: 'timeout',
    });
  });

  it('maps other terminal error events to a server ApiError', async () => {
    mockFetch('event: error\ndata: {"detail":"Internal server error"}\n\n');

    await expect(postQueryStream('a question', [], handlers())).rejects.toMatchObject({
      type: 'server',
    });
  });

  it('a stream that ends without final is a server error', async () => {
    mockFetch('event: token\ndata: {"text":"Hel"}\n\n');

    await expect(postQueryStream('a question', [], handlers())).rejects.toBeInstanceOf(
      ApiErrorInstance,
    );
  });

  it('maps HTTP 429 like postQuery, with retryAfter', async () => {
    global.fetch = jest.fn().mockResolvedValue(
      new Response(JSON.stringify({ detail: 'Rate limit exceeded.' }), {
        status: 429,
        headers: { 'Content-Type': 'application/json', 'Retry-After': '30' },
      }),
    ) as unknown as typeof fetch;

    await expect(postQueryStream('a question', [], handlers())).rejects.toMatchObject({
      type: 'rate_limit',
      retryAfter: 30,
    });
  });

  it('sends question and card_mentions to /api/query/stream', async () => {
    mockFetch(SSE_BODY);

    await postQueryStream('a question', ['tideturner'], handlers());

    const [url, init] = (global.fetch as jest.Mock).mock.calls[0];
    expect(url).toBe('/api/query/stream');
    expect(JSON.parse(init.body)).toEqual({ question: 'a question', card_mentions: ['tideturner'] });
  });
});
