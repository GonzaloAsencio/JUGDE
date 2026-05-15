import type { QueryResponse } from './types';

export async function postQuery(question: string): Promise<QueryResponse> {
  const res = await fetch('/api/query', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ question }),
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw Object.assign(new Error(body.detail ?? 'Query failed'), { status: res.status });
  }
  return res.json() as Promise<QueryResponse>;
}
