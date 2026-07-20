import crypto from 'crypto';
import { NextRequest, NextResponse } from 'next/server';

/**
 * Shared plumbing for the /api/query* proxy routes. Extracted so the blocking
 * route and the SSE route cannot drift on auth headers, IP forwarding, body
 * validation, or upstream error mapping.
 */

export const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000';

// Anonymous identity cookie (Fase 5 metering). The proxy MINTS and SIGNS the
// id; the backend only honors the resulting X-User-Id behind the proxy secret,
// so the signature's job is integrity within our own boundary — a tampered
// cookie must not silently become a different user's quota bucket. Secret is
// JUDGE_UID_SECRET, deliberately DISTINCT from PROXY_SHARED_SECRET (different
// blast radius: leaking one must not compromise the other).
const UID_COOKIE = 'judge_uid';
const UID_MAX_AGE_S = 60 * 60 * 24 * 365; // 1 year — an anonymous id should persist

function signUid(uuid: string, secret: string): string {
  return crypto.createHmac('sha256', secret).update(uuid).digest('base64url');
}

// Returns the uuid iff *value* ("{uuid}.{sig}") carries a valid signature.
// Constant-time compare so a forged cookie can't be brute-forced byte by byte.
function verifyUid(value: string, secret: string): string | null {
  const dot = value.lastIndexOf('.');
  if (dot <= 0) return null;
  const uuid = value.slice(0, dot);
  const sig = value.slice(dot + 1);
  const expected = signUid(uuid, secret);
  const a = Buffer.from(sig);
  const b = Buffer.from(expected);
  if (a.length !== b.length || !crypto.timingSafeEqual(a, b)) return null;
  return uuid;
}

export interface JudgeUid {
  /** "anon:{uuid}" to forward as X-User-Id, or "" when no secret is configured. */
  userId: string;
  /** A Set-Cookie value present ONLY when the cookie was (re)minted this request. */
  setCookie?: string;
}

/**
 * Resolve the caller's anonymous id from the signed cookie, minting a fresh
 * one when it is missing or fails verification.
 *
 * Without JUDGE_UID_SECRET (local dev) there is nothing to sign with, and the
 * backend ignores X-User-Id anyway when PROXY_SHARED_SECRET is unset — so we
 * return an empty id and let the backend fall back to per-IP metering.
 */
function readCookie(req: NextRequest, name: string): string | undefined {
  // Parse the raw Cookie header rather than NextRequest.cookies: it works
  // identically for the plain Request objects the route unit tests construct,
  // and NextRequest.cookies is just a parser over this same header.
  const raw = req.headers.get('cookie');
  if (!raw) return undefined;
  for (const part of raw.split('; ')) {
    const eq = part.indexOf('=');
    if (eq > 0 && part.slice(0, eq) === name) return part.slice(eq + 1);
  }
  return undefined;
}

export function ensureJudgeUid(req: NextRequest): JudgeUid {
  const secret = process.env.JUDGE_UID_SECRET;
  if (!secret) return { userId: '' };

  const existing = readCookie(req, UID_COOKIE);
  if (existing) {
    const uuid = verifyUid(existing, secret);
    if (uuid) return { userId: `anon:${uuid}` };
  }

  const uuid = crypto.randomUUID();
  const value = `${uuid}.${signUid(uuid, secret)}`;
  // Secure + HttpOnly + Lax: the client never needs to read it (the proxy owns
  // identity), and Lax keeps it on top-level navigations without exposing it
  // to cross-site requests.
  const setCookie =
    `${UID_COOKIE}=${value}; Max-Age=${UID_MAX_AGE_S}; Path=/; HttpOnly; Secure; SameSite=Lax`;
  return { userId: `anon:${uuid}`, setCookie };
}

/** Attach a mint's Set-Cookie to any response, passing through when absent. */
export function withUidCookie<T extends NextResponse | Response>(res: T, uid: JudgeUid): T {
  if (uid.setCookie) res.headers.set('Set-Cookie', uid.setCookie);
  return res;
}

/**
 * Resolve the caller's identity for a request: a valid Supabase session wins
 * (forward `auth:{sub}`, no anon cookie needed), otherwise the signed anon
 * cookie (minted if absent).
 *
 * The auth id is validated SERVER-SIDE via getUser() — never taken from a
 * client-set value — so a logged-in user's tier can't be forged. When no
 * session exists we fall through to the anonymous identity, so logout and
 * un-configured deploys keep metering by anon cookie / IP.
 */
export async function resolveIdentity(req: NextRequest): Promise<JudgeUid> {
  // Lazy import keeps @supabase/ssr out of routes that only ever run anon
  // (and out of the unit tests that mock it explicitly).
  const { getAuthUserId } = await import('@/lib/supabase/server');
  const authUserId = await getAuthUserId(req);
  if (authUserId) return { userId: authUserId };
  return ensureJudgeUid(req);
}

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

export function buildProxyHeaders(req: NextRequest, userId?: string): Record<string, string> {
  const headers: Record<string, string> = { 'Content-Type': 'application/json' };

  // Shared secret: proves to the backend that this request comes from the
  // trusted proxy (enables auth + per-user rate limiting backend-side).
  const proxySecret = process.env.PROXY_SHARED_SECRET;
  if (proxySecret) headers['X-Proxy-Secret'] = proxySecret;

  // Anonymous identity for token metering. The backend honors this only behind
  // the proxy secret above, so a forged header from a real client is ignored.
  if (userId) headers['X-User-Id'] = userId;

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
