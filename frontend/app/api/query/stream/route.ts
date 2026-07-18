import { NextRequest, NextResponse } from 'next/server';
import { FASTAPI_URL, buildProxyHeaders, mapUpstreamError, parseQueryBody } from '@/lib/proxy';

const CONNECT_TIMEOUT_MS = Number(process.env.FASTAPI_TIMEOUT_MS ?? 30_000);

// Streaming generations legitimately outlive the default function budget;
// the platform cap is the real upper bound on a stream's lifetime.
export const maxDuration = 60;

export async function POST(req: NextRequest) {
  const body = await req.json().catch(() => null);
  const parsed = parseQueryBody(body);
  if (!parsed) {
    return NextResponse.json({ detail: 'question is required' }, { status: 400 });
  }

  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), CONNECT_TIMEOUT_MS);

  try {
    const upstream = await fetch(`${FASTAPI_URL}/api/v1/query/stream`, {
      method: 'POST',
      headers: buildProxyHeaders(req),
      body: JSON.stringify({ question: parsed.question, card_mentions: parsed.cardMentions }),
      signal: controller.signal,
    });

    // fetch resolves when the HEADERS arrive — the timeout guards connection +
    // backend acceptance only. From here the body streams for as long as the
    // generation takes, so the timer must not be allowed to kill it mid-stream.
    clearTimeout(timer);

    if (!upstream.ok || !upstream.body) {
      return mapUpstreamError(upstream);
    }

    // Hand the upstream ReadableStream straight to the Response: buffering it
    // here would collapse the SSE stream into one flush, undoing the feature.
    return new Response(upstream.body, {
      status: 200,
      headers: {
        'Content-Type': 'text/event-stream; charset=utf-8',
        'Cache-Control': 'no-cache',
      },
    });
  } catch (err: unknown) {
    clearTimeout(timer);
    if (err instanceof Error && err.name === 'AbortError') {
      return NextResponse.json({ detail: 'The judge took too long. Try again.' }, { status: 504 });
    }
    return NextResponse.json({ detail: 'Something went wrong. Try again.' }, { status: 500 });
  }
}
