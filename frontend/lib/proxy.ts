import { NextRequest, NextResponse } from 'next/server';

/**
 * Shared plumbing for the /api/query* proxy routes. Extracted so the blocking
 * route and the SSE route cannot drift on auth headers, IP forwarding, body
 * validation, or upstream error mapping.
 */

export const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000';

export interface ParsedQueryBody {
  question: string;
  cardMentions: string[];
}

export function parseQueryBody(body: unknown): ParsedQueryBody | null {
  const candidate = body as { question?: unknown; card_mentions?: unknown } | null;
  if (!candidate?.question || typeof candidate.question !== 'string') return null;
  const cardMentions: string[] = Array.isArray(candidate.card_mentions)
    ? candidate.card_mentions.filter((m: unknown): m is string => typeof m === 'string')
    : [];
  return { question: candidate.question, cardMentions };
}

export function buildProxyHeaders(req: NextRequest): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };

  // Shared secret: proves to the backend that this request comes from the
  // trusted proxy (enables auth + per-user rate limiting backend-side).
  const proxySecret = process.env.PROXY_SHARED_SECRET;
  if (proxySecret) headers['X-Proxy-Secret'] = proxySecret;

  // Real client IP (first hop of x-forwarded-for) so the backend rate-limits
  // per user instead of per proxy egress IP.
  //
  // INFRASTRUCTURE ASSUMPTION: trusting the FIRST hop is only safe because
  // Vercel overwrites x-forwarded-for with the real client IP (client-supplied
  // values are discarded). If this proxy ever moves off Vercel, the first hop
  // becomes client-controlled: an attacker spoofs a fresh IP per request, gets
  // unlimited rate-limit buckets, and burns the daily Gemini quota. On any
  // other host, switch to the platform's trusted client-IP header or the
  // rightmost untrusted hop.
  const realIp = req.headers.get('x-forwarded-for')?.split(',')[0]?.trim();
  if (realIp) headers['X-Real-IP'] = realIp;

  return headers;
}

export async function mapUpstreamError(upstream: Response): Promise<NextResponse> {
  if (upstream.status === 429) {
    const err = await upstream.json().catch(() => ({ detail: 'Rate limit exceeded.' }));
    const retryAfter = upstream.headers.get('Retry-After');
    const headers: Record<string, string> = {};
    if (retryAfter) headers['Retry-After'] = retryAfter;
    return NextResponse.json(err, { status: 429, headers });
  }

  if (upstream.status === 504) {
    return NextResponse.json({ detail: 'The judge took too long. Try again.' }, { status: 504 });
  }
  // 401 = proxy/backend secret mismatch (deploy misconfig) — never the
  // user's fault; don't leak the auth detail to the client.
  if (upstream.status === 401 || upstream.status === 502 || upstream.status === 503) {
    return NextResponse.json({ detail: 'Service temporarily unavailable.' }, { status: 503 });
  }
  if (upstream.status >= 400 && upstream.status < 500) {
    const err = await upstream.json().catch(() => ({ detail: 'Bad request.' }));
    return NextResponse.json(err, { status: upstream.status });
  }
  return NextResponse.json({ detail: 'Something went wrong. Try again.' }, { status: 500 });
}
