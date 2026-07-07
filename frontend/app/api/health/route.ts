import { NextResponse } from 'next/server';

const FASTAPI_URL = process.env.FASTAPI_URL ?? 'http://localhost:8000';
const TIMEOUT_MS = 5_000;

// Lets the client distinguish "backend genuinely down" from "HF Space is asleep
// and waking up" without waiting through the full query timeout. /health is
// exempt from the shared-secret auth middleware backend-side, so no secret here.
export async function GET() {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TIMEOUT_MS);

  try {
    const upstream = await fetch(`${FASTAPI_URL}/health`, { signal: controller.signal });
    clearTimeout(timer);
    if (upstream.ok) {
      return NextResponse.json({ status: 'ok' });
    }
    return NextResponse.json({ status: 'unavailable' }, { status: 503 });
  } catch {
    clearTimeout(timer);
    return NextResponse.json({ status: 'unavailable' }, { status: 503 });
  }
}
