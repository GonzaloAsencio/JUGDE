# Optional login (Supabase Auth + Google OAuth)

Login is **optional** and only **raises the daily token limit** — anonymous use
keeps working with the lower quota. Everything runs on the **free tier**:
Supabase Auth on the *same* Supabase project already used for Postgres, and
Google OAuth (zero emails — the free-tier SMTP is capped, so no magic links).

## Deploy order

The login is deployed **after** anonymous metering is verified in prod (the
two-step flip of the metering flag). This PR is frontend + configuration only —
the backend is unchanged: the `auth:` prefix on `X-User-Id` already selects the
higher-quota tier (added with the quota core).

## One-time Supabase dashboard setup (user action)

1. **Enable the Google provider**: Supabase dashboard → *Authentication* →
   *Providers* → *Google* → enable.
2. **Create Google OAuth credentials**: Google Cloud Console → *APIs & Services*
   → *Credentials* → *OAuth client ID* (type *Web application*). Copy the client
   ID and secret into the Supabase Google provider form.
3. **Authorized redirect URI** (in Google Cloud, on the OAuth client):
   `https://<your-supabase-ref>.supabase.co/auth/v1/callback`
4. **Redirect URLs** (Supabase → *Authentication* → *URL Configuration* → *Redirect URLs*):
   add `https://<your-vercel-domain>/auth/callback` (and
   `http://localhost:3000/auth/callback` for local dev).

## Environment variables (Vercel)

Both are **public** (the anon key is designed for the browser):

```
NEXT_PUBLIC_SUPABASE_URL=https://<your-supabase-ref>.supabase.co
NEXT_PUBLIC_SUPABASE_ANON_KEY=<your-anon-key>
```

Without these, the login UI hides itself and the app runs anonymous-only — a
deploy that hasn't configured Supabase Auth is not broken, it just has no login.

## How identity flows

- Logged out: the Next proxy mints a signed anonymous cookie (`judge_uid`) and
  forwards `X-User-Id: anon:{uuid}`.
- Logged in: the proxy validates the Supabase session **server-side**
  (`getUser()` re-checks the JWT — the client-sent id is never trusted) and
  forwards `X-User-Id: auth:{sub}` instead, which the backend maps to the higher
  tier. Sign out clears the session and the next request is anonymous again.

## Token-count accuracy (`estimated` flag)

Each `usage` reports an `estimated` boolean. Counts are **real** when the LLM
API returns a usage object (`response.usage` for OpenAI-compat, `usage_metadata`
for Gemini); otherwise the pipeline falls back to a `chars/4` estimate and marks
`estimated: true`. Estimation never blocks or breaks a query — an accurate meter
is not worth failing an answer over.

Verified locally against the real backend: **Cerebras (`gpt-oss-120b`) does not
return a `usage` object on non-streaming `/query` calls**, so those land as
`estimated: true`. The number is a reasonable approximation, not exact. Two ways
to get real counts for Cerebras if precision ever matters:

- Prefer the **streaming** path (`/query/stream`) and confirm Cerebras emits a
  trailing usage chunk — the streamers already capture it via `on_usage`.
- Send `stream_options={"include_usage": true}` on the stream request. It is
  deliberately **off** today because not every OpenAI-compat server accepts it,
  and a rejected request would kill streaming just to obtain a metric. Enable it
  only after confirming the live provider accepts it (see PR #82).

Gemini (the hard-routed model) returns `usage_metadata`, so routed queries are
counted for real, thinking tokens included.

## Privacy / data retention

With real login there is now an email in **Supabase Auth**. The **usage ledger
still stores zero PII**: only the opaque `auth:{sub}` and token counts — never
the email, never the question text. Supabase Auth holds the email under its own
retention; the application database does not copy it. (BYOK — bringing your own
model key — is intentionally left for a future iteration; the ledger's `model`
column leaves the door open.)
