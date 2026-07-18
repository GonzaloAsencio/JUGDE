import { NextRequest, NextResponse } from 'next/server';
import { FASTAPI_URL, buildProxyHeaders, mapUpstreamError, parseQueryBody } from '@/lib/proxy';

const TIMEOUT_MS = Number(process.env.FASTAPI_TIMEOUT_MS ?? 30_000);

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = parseQueryBody(body);
  if (!parsed) {
    return NextResponse.json({ detail: 'question is required' }, { status: 400 });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const upstream = await fetch(`${FASTAPI_URL}/api/v1/query`, {
      method: 'POST',
      headers: buildProxyHeaders(req),
      body: JSON.stringify({ question: parsed.question, card_mentions: parsed.cardMentions }),
      signal: controller.signal,
    });

    clearTimeout(timer);

    if (upstream.ok) {
      const data = await upstream.json();
      return NextResponse.json(data);
    }

    return mapUpstreamError(upstream);
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof Error && err.name === 'AbortError') {
      return NextResponse.json({ detail: 'The judge took too long. Try again.' }, { status: 504 });
    }
    return NextResponse.json({ detail: 'Something went wrong. Try again.' }, { status: 500 });
  }
}
