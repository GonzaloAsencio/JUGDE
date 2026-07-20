import { NextRequest, NextResponse } from 'next/server';
import { FASTAPI_URL, buildProxyHeaders, ensureJudgeUid, withUidCookie } from '@/lib/proxy';

const TIMEOUT_MS = 5_000;

/**
 * GET /api/usage — proxy the caller's daily token meter from the backend.
 *
 * Same identity resolution as the query routes (a first visit to /usage mints
 * the anon cookie too), so the badge shows a real bucket even before the first
 * question. On any failure it degrades to null: the badge is ambient, never a
 * blocking dependency.
 */
export async function GET(req: NextRequest) {
  const uid = ensureJudgeUid(req);
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const upstream = await fetch(`${FASTAPI_URL}/api/v1/usage`, {
      method: 'GET',
      headers: buildProxyHeaders(req, uid.userId),
      signal: controller.signal,
    });
    clearTimeout(timer);

    if (!upstream.ok) {
      return withUidCookie(NextResponse.json({ detail: 'usage unavailable' }, { status: 503 }), uid);
    }
    const data = await upstream.json();
    return withUidCookie(NextResponse.json(data), uid);
  } catch {
    clearTimeout(timer);
    return withUidCookie(NextResponse.json({ detail: 'usage unavailable' }, { status: 503 }), uid);
  }
}
