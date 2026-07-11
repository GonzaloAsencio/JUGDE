import { NextRequest, NextResponse } from 'next/server';

const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000';
const TIMEOUT_MS = Number(process.env.FASTAPI_TIMEOUT_MS ?? 30_000);

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  if (!body?.question || typeof body.question !== 'string') {
    return NextResponse.json({ detail: 'question is required' }, { status: 400 });
  }

  const cardMentions: string[] = Array.isArray(body.card_mentions)
    ? body.card_mentions.filter((m: unknown): m is string => typeof m === 'string')
    : [];

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

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

  try {
    const upstream = await fetch(`${FASTAPI_URL}/api/v1/query`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ question: body.question, card_mentions: cardMentions }),
      signal: controller.signal,
    });

    clearTimeout(timer);

    if (upstream.ok) {
      const data = await upstream.json();
      return NextResponse.json(data);
    }

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
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof Error && err.name === 'AbortError') {
      return NextResponse.json({ detail: 'The judge took too long. Try again.' }, { status: 504 });
    }
    return NextResponse.json({ detail: 'Something went wrong. Try again.' }, { status: 500 });
  }
}
