import { ApiErrorInstance, mapError } from './api';
import type { QueryResponse } from './types';

// Idle timeout, not total: a streaming answer legitimately runs for minutes,
// but 60s with NO events means the stream is dead.
const IDLE_TIMEOUT_MS = 60_000;

export interface SseEvent {
  event: string;
  data: unknown;
}

/**
 * Incrementally parse an SSE byte stream into events. Frames arrive split
 * across arbitrary chunk boundaries, so bytes buffer until a full
 * ``\n\n``-terminated frame is available.
 */
export async function* sseEvents(body: ReadableStream<Uint8Array>): AsyncGenerator<SseEvent> {
  const reader = body.getReader();
  const decoder = new TextDecoder();
  let buffer = '';
  try {
    for (;;) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      let sep = buffer.indexOf('\n\n');
      while (sep !== -1) {
        const frame = buffer.slice(0, sep);
        buffer = buffer.slice(sep + 2);
        let event = 'message';
        let data: unknown = null;
        for (const line of frame.split('\n')) {
          if (line.startsWith('event: ')) {
            event = line.slice('event: '.length);
          } else if (line.startsWith('data: ')) {
            try {
              data = JSON.parse(line.slice('data: '.length));
            } catch {
              data = null;
            }
          }
        }
        yield { event, data };
        sep = buffer.indexOf('\n\n');
      }
    }
  } finally {
    reader.releaseLock();
  }
}

export interface StreamHandlers {
  onToken: (text: string) => void;
  onRestart: () => void;
}

/**
 * POST /api/query/stream and drive *handlers* with the event stream.
 * Resolves with the FINAL canonical QueryResponse (the caller replaces its
 * progressively displayed text with it). Throws ApiErrorInstance with the
 * same mapping as postQuery — a terminal in-band ``error`` event carries the
 * backend's /query error details, delivered mid-stream where the HTTP status
 * can no longer change.
 */
export async function postQueryStream(
  question: string,
  cardMentions: string[],
  handlers: StreamHandlers,
): Promise<QueryResponse> {
  const controller = new AbortController();
  let timer = setTimeout(() => controller.abort(), IDLE_TIMEOUT_MS);
  const bumpIdle = () => {
    clearTimeout(timer);
    timer = setTimeout(() => controller.abort(), IDLE_TIMEOUT_MS);
  };

  try {
    const res = await fetch('/api/query/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question, card_mentions: cardMentions }),
      signal: controller.signal,
    });

    if (!res.ok || !res.body) {
      const body = await res.json().catch(() => ({})) as Record<string, unknown>;
      const err = mapError(res, body);
      throw new ApiErrorInstance(err.type, err.message, err.retryAfter);
    }

    for await (const { event, data } of sseEvents(res.body)) {
      bumpIdle();
      if (event === 'token') {
        handlers.onToken((data as { text?: string })?.text ?? '');
      } else if (event === 'restart') {
        handlers.onRestart();
      } else if (event === 'final') {
        return data as QueryResponse;
      } else if (event === 'error') {
        const detail = String((data as { detail?: string })?.detail ?? 'Something went wrong.');
        throw new ApiErrorInstance(/timeout/i.test(detail) ? 'timeout' : 'server', detail);
      }
    }
    throw new ApiErrorInstance('server', 'The answer stream ended unexpectedly. Try again.');
  } catch (err: unknown) {
    if (err instanceof ApiErrorInstance) throw err;
    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiErrorInstance('timeout', 'This is taking too long. Try again.');
    }
    throw new ApiErrorInstance('network', 'Connection error. Check your internet.');
  } finally {
    clearTimeout(timer);
  }
}
