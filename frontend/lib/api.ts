import type { ApiError, ErrorType, QueryResponse } from './types';

const CLIENT_TIMEOUT_MS = 10_000;

export class ApiErrorInstance extends Error {
  type: ErrorType;
  retryAfter?: number;

  constructor(type: ErrorType, message: string, retryAfter?: number) {
    super(message);
    this.name = 'ApiError';
    this.type = type;
    this.retryAfter = retryAfter;
  }
}

function mapError(res: Response, body: Record<string, unknown>): ApiError {
  const message = typeof body.detail === 'string' ? body.detail : 'Something went wrong.';

  if (res.status === 429) {
    const retryAfterHeader = res.headers.get('Retry-After');
    const retryAfter = retryAfterHeader ? parseInt(retryAfterHeader, 10) : undefined;
    return { type: 'rate_limit', message, retryAfter };
  }

  if (res.status === 422) {
    return { type: 'validation', message };
  }

  if (res.status === 504) {
    return { type: 'timeout', message: 'This is taking too long. Try again.' };
  }

  if (res.status >= 500) {
    return { type: 'server', message: 'Something went wrong on our end. Try again.' };
  }

  return { type: 'unknown', message };
}

export async function postQuery(question: string): Promise<QueryResponse> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CLIENT_TIMEOUT_MS);

  try {
    const res = await fetch('/api/query', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question }),
      signal: controller.signal,
    });

    clearTimeout(timer);

    if (res.ok) {
      return res.json() as Promise<QueryResponse>;
    }

    const body = await res.json().catch(() => ({})) as Record<string, unknown>;
    const err = mapError(res, body);
    throw new ApiErrorInstance(err.type, err.message, err.retryAfter);
  } catch (err: unknown) {
    clearTimeout(timer);

    if (err instanceof ApiErrorInstance) {
      throw err;
    }

    if (err instanceof Error && err.name === 'AbortError') {
      throw new ApiErrorInstance('timeout', 'This is taking too long. Try again.');
    }

    throw new ApiErrorInstance('network', 'Connection error. Check your internet.');
  }
}
