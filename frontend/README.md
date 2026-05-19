# Riftbound Judge — Frontend

Next.js frontend for the Riftbound Judge AI.

## Environment Variables

| Variable | Description |
|---|---|
| `FASTAPI_URL` | URL of the backend API (e.g. `https://gonzaviss-judge.hf.space`) |

## Development

```bash
npm install
cp .env.example .env.local  # set FASTAPI_URL=http://localhost:8000
npm run dev
```

## Deploy

Deployed on Vercel. Set `FASTAPI_URL` in Project Settings → Environment Variables.
