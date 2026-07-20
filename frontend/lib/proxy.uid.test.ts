/**
 * @jest-environment node
 *
 * Anonymous identity cookie (Fase 5 metering): the proxy mints a signed uid,
 * verifies it on return visits, and rejects tampering. buildProxyHeaders only
 * forwards X-User-Id when we actually have one.
 */
import { NextRequest } from 'next/server';
import crypto from 'crypto';

import { buildProxyHeaders, ensureJudgeUid } from './proxy';

const ORIGINAL_ENV = process.env;
const SECRET = 'uid-secret';

function reqWithCookie(cookie?: string): NextRequest {
  const headers: Record<string, string> = {};
  if (cookie) headers['cookie'] = cookie;
  return new NextRequest('http://localhost/api/query', { headers });
}

function parseCookie(setCookie: string): { name: string; value: string; attrs: string } {
  const [pair, ...rest] = setCookie.split('; ');
  const eq = pair.indexOf('=');
  return { name: pair.slice(0, eq), value: pair.slice(eq + 1), attrs: rest.join('; ') };
}

beforeEach(() => {
  process.env = { ...ORIGINAL_ENV, JUDGE_UID_SECRET: SECRET };
});
afterEach(() => {
  process.env = ORIGINAL_ENV;
});

describe('ensureJudgeUid', () => {
  it('mints a signed anon uid when no cookie is present', () => {
    const uid = ensureJudgeUid(reqWithCookie());

    expect(uid.userId).toMatch(/^anon:[0-9a-f-]{36}$/);
    expect(uid.setCookie).toBeDefined();
    const { name, value, attrs } = parseCookie(uid.setCookie!);
    expect(name).toBe('judge_uid');
    expect(value).toBe(`${uid.userId.slice('anon:'.length)}.${crypto.createHmac('sha256', SECRET).update(uid.userId.slice('anon:'.length)).digest('base64url')}`);
    expect(attrs).toContain('HttpOnly');
    expect(attrs).toContain('Secure');
    expect(attrs).toContain('SameSite=Lax');
    expect(attrs).toContain('Max-Age=31536000');
  });

  it('honors a valid signed cookie without re-minting', () => {
    const minted = ensureJudgeUid(reqWithCookie());
    const { value } = parseCookie(minted.setCookie!);

    const returning = ensureJudgeUid(reqWithCookie(`judge_uid=${value}`));

    expect(returning.userId).toBe(minted.userId);
    expect(returning.setCookie).toBeUndefined();
  });

  it('re-mints when the signature does not match (tampered uuid)', () => {
    const uid = ensureJudgeUid(reqWithCookie());
    const { value } = parseCookie(uid.setCookie!);
    const sig = value.split('.')[1];

    const tampered = ensureJudgeUid(reqWithCookie(`judge_uid=evil-uuid.${sig}`));

    expect(tampered.userId).not.toBe(uid.userId);
    expect(tampered.userId).not.toContain('evil-uuid');
    expect(tampered.setCookie).toBeDefined();
  });

  it('re-mints when the cookie has no signature', () => {
    const tampered = ensureJudgeUid(reqWithCookie('judge_uid=just-a-uuid'));

    expect(tampered.setCookie).toBeDefined();
  });

  it('returns an empty id and mints nothing without JUDGE_UID_SECRET', () => {
    delete process.env.JUDGE_UID_SECRET;

    const uid = ensureJudgeUid(reqWithCookie());

    expect(uid.userId).toBe('');
    expect(uid.setCookie).toBeUndefined();
  });

  it('uses a secret distinct from PROXY_SHARED_SECRET (a proxy secret alone does not sign)', () => {
    delete process.env.JUDGE_UID_SECRET;
    process.env.PROXY_SHARED_SECRET = 'proxy-only';

    expect(ensureJudgeUid(reqWithCookie()).userId).toBe('');
  });
});

describe('buildProxyHeaders X-User-Id', () => {
  it('forwards X-User-Id when a userId is given', () => {
    const headers = buildProxyHeaders(reqWithCookie(), 'anon:abc');
    expect(headers['X-User-Id']).toBe('anon:abc');
  });

  it('omits X-User-Id when the userId is empty', () => {
    const headers = buildProxyHeaders(reqWithCookie(), '');
    expect(headers['X-User-Id']).toBeUndefined();
  });
});
