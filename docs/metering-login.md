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

## Privacy / data retention

With real login there is now an email in **Supabase Auth**. The **usage ledger
still stores zero PII**: only the opaque `auth:{sub}` and token counts — never
the email, never the question text. Supabase Auth holds the email under its own
retention; the application database does not copy it. (BYOK — bringing your own
model key — is intentionally left for a future iteration; the ledger's `model`
column leaves the door open.)
