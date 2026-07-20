/**
 * @jest-environment node
 *
 * resolveIdentity: a valid Supabase session wins (auth:{sub}, no anon cookie);
 * otherwise it falls back to the signed anon cookie. The auth id is always
 * validated server-side — never taken from the client.
 */
import { NextRequest } from 'next/server';

const getAuthUserId = jest.fn();
jest.mock('@/lib/supabase/server', () => ({ getAuthUserId: (...a: unknown[]) => getAuthUserId(...a) }));

import { resolveIdentity } from './proxy';

const ORIGINAL_ENV = process.env;

function req(cookie?: string): NextRequest {
  const headers: Record<string, string> = {};
  if (cookie) headers['cookie'] = cookie;
  return new NextRequest('http://localhost/api/query', { headers });
}

beforeEach(() => {
  process.env = { ...ORIGINAL_ENV, JUDGE_UID_SECRET: 'uid-secret' };
  getAuthUserId.mockReset();
});
afterEach(() => {
  process.env = ORIGINAL_ENV;
});

it('forwards auth:{sub} and mints no anon cookie when a session is valid', async () => {
  getAuthUserId.mockResolvedValue('auth:sub-123');

  const uid = await resolveIdentity(req());

  expect(uid.userId).toBe('auth:sub-123');
  expect(uid.setCookie).toBeUndefined();
});

it('falls back to a minted anon identity when there is no session', async () => {
  getAuthUserId.mockResolvedValue(null);

  const uid = await resolveIdentity(req());

  expect(uid.userId).toMatch(/^anon:/);
  expect(uid.setCookie).toBeDefined();
});

it('reuses an existing anon cookie when logged out', async () => {
  getAuthUserId.mockResolvedValue(null);
  const first = await resolveIdentity(req());
  const cookieValue = first.setCookie!.split(';')[0].split('=')[1];

  const second = await resolveIdentity(req(`judge_uid=${cookieValue}`));

  expect(second.userId).toBe(first.userId);
  expect(second.setCookie).toBeUndefined();
});
