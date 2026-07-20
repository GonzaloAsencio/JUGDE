import type { ApiError, ErrorType } from './types';

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

// Exported for streamQuery: the SSE client must map HTTP errors identically.
export function mapError(res: Response, body: Record<string, unknown>): ApiError {
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

const HEALTH_TIMEOUT_MS = 5_000;

// Fast probe used to tell a genuine cold start (HF Space asleep) apart from a
// one-off transient error, and later to poll until the Space wakes back up.
// Never throws — a failed probe is just `false`.
export async function pingHealth(): Promise<boolean> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), HEALTH_TIMEOUT_MS);
  try {
    const res = await fetch('/api/health', { signal: controller.signal });
    return res.ok;
  } catch {
    return false;
  } finally {
    clearTimeout(timer);
  }
}
