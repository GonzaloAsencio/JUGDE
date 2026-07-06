# Local Setup & Testing Guide

Step-by-step guide to run the backend, the frontend, and the eval harness locally, and confirm each one actually works. Every command below was executed against this repo before being written down — none of this is theoretical.

For the high-level architecture and feature list, see the root [README.md](../README.md). This doc is narrower: it only covers "how do I run it and how do I know it's working."

---

## Prerequisites

- Python 3.11+ (tested here on 3.14)
- Node.js 18+ (tested here on 24)
- A Supabase (or any Postgres 15+) instance with `pgvector` enabled, corpus already ingested (see `backend/scripts/ingest.py` in the root README)
- An LLM credential — either `GEMINI_API_KEY`, or a full `openai_compat` config (Groq, LM Studio, Ollama, etc.)

---

## 1. Environment variables

### Backend (`backend/.env`)

Copy `backend/.env.example` to `backend/.env` and fill in:

| Variable | Required? | Meaning |
|---|---|---|
| `DATABASE_URL` | **Required** | Postgres connection string (Supabase). Without it, `Settings()` raises at import time. |
| `LLM_PROVIDER` | Optional (default `gemini`) | `gemini` or `openai_compat`. |
| `GEMINI_API_KEY` | Required **if** `LLM_PROVIDER=gemini` | Free tier at [aistudio.google.com](https://aistudio.google.com). |
| `LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL` | Required **together** if `LLM_PROVIDER=openai_compat` | Missing any one of the three makes `Settings()` raise on startup (`_check_provider_fields` validator). |
| `JUDGE_BASE_URL` / `JUDGE_API_KEY` / `JUDGE_MODEL` | Optional | Dedicated LLM for the eval judge. If unset, the judge falls back to `LLM_*` (shares quota with the pipeline) or `GEMINI_API_KEY`. |
| `PROXY_SHARED_SECRET` | Optional locally, **required in production** | When set, every endpoint except `/health` requires an `X-Proxy-Secret` header. `app_env=production` + no secret = the app refuses to start (fail-closed). Leave it unset for local-only testing, or set it and let the frontend proxy forward it automatically. |
| `UPSTASH_REDIS_URL` / `UPSTASH_REDIS_TOKEN` | Optional | Response cache. Disabled if absent. |
| `SENTRY_DSN` | Optional | Error reporting. Disabled if absent. |
| `LANGFUSE_PUBLIC_KEY` / `LANGFUSE_SECRET_KEY` | Optional | LLM tracing. Disabled if absent. |
| `CORPUS_VERSION` | Optional | Pins retrieval to a specific ingested corpus version. Leave unset/`latest` to auto-resolve the max version in the DB. |
| `TOP_K` / `TOP_K_FETCH` | Optional | Retrieval tuning (defaults: 5 / 15). |

### Frontend (`frontend/.env.local`)

| Variable | Required? | Meaning |
|---|---|---|
| `FASTAPI_URL` | **Required** | Where the backend lives, e.g. `http://localhost:8000`. |
| `PROXY_SHARED_SECRET` | Required **only if** the backend has one set | Must match the backend's value exactly — mismatch or one-sided config means every query 503s. |

---

## 2. Run the backend

```bash
cd backend
python -m venv venv
venv\Scripts\activate          # Windows
# source venv/bin/activate     # macOS/Linux

pip install -r requirements.txt
pip install -r requirements-dev.txt   # only if you'll run pytest/eval/ingest scripts

uvicorn app.main:app --reload --port 8000
```

**First-run note**: startup downloads `BAAI/bge-m3` (~1.2 GB) from Hugging Face and loads it onto CPU — expect the first boot to take noticeably longer than `--reload` restarts. You'll see a wall of `HTTP Request: HEAD https://huggingface.co/...` log lines; that's normal, not an error.

**Verify it's alive**:

```bash
curl http://localhost:8000/health
```

Expected output:

```json
{"status":"ok","version":"0.1.0","corpus_version":"v2.1.0","timestamp":"..."}
```

If `corpus_version` is missing or the endpoint hangs on DB init, the corpus hasn't been ingested yet, or `DATABASE_URL` is wrong.

**Verify a real query** (only needed if you didn't set `PROXY_SHARED_SECRET`, otherwise test through the frontend proxy instead — see below):

```bash
curl -X POST http://localhost:8000/api/v1/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the golden rule?"}'
```

Expected: a JSON body with `answer`, `citations` (array with `section`, `similarity`, `content_preview`), and `confidence`. A 503 here (with the secret unset) usually means the DB pool is exhausted or the corpus table is empty.

---

## 3. Run the frontend

```bash
cd frontend
npm install
npm run dev     # http://localhost:3000
```

**Verify it's alive**: open `http://localhost:3000` in a browser, or:

```bash
curl -o /dev/null -w "%{http_code}\n" http://localhost:3000
# expect: 200
```

**Verify the full pipeline through the proxy** (this is the same path the browser uses, and it auto-injects `X-Proxy-Secret` if configured — you don't need to know the secret value to test this):

```bash
curl -X POST http://localhost:3000/api/query \
  -H "Content-Type: application/json" \
  -d '{"question":"What is the golden rule?"}'
```

Expected: same shape as the backend response above. If this 503s but the direct backend curl above worked, the secret in `frontend/.env.local` doesn't match the backend's.

---

## 4. Run the eval

```bash
cd backend
python -m scripts.eval --limit 2      # small subset — cheap, fast smoke test
python -m scripts.eval                # full 20-question set
```

Requires: DB with corpus ingested, plus a working LLM provider (pipeline) and judge (`JUDGE_*`, or fallback to `LLM_*`/`GEMINI_API_KEY`). The Redis cache is intentionally bypassed — every question hits generation fresh, so a full run is not free/instant.

**Expected output** — a per-question line, then a summary block:

```
[ 1/2] If I play Marching Orders with Repeat, do both damage i... NO ret=- conf=1.00 11737ms
[ 2/2] Does Vex Apathetic's ability create a chain? Can you mi... OK ret=- conf=1.00 9964ms

============================================================
EVAL RESULTS
============================================================
  Total questions : 2
  Accuracy (judge): correct=1 partial=0 wrong=1 error=0
  Correct rate    : 50%  (correct+partial: 50%)
  Retrieval recall: 0/0 evaluable questions = 0%
  Avg confidence  : 1.000
  Avg latency     : 10850ms
  ...
Results saved: backend/data/eval_results_<timestamp>.json
```

`NO`/`OK`/`~~`/`ER` = wrong/correct/partial/pipeline-error per question. An `ER` on every question means the pipeline itself is broken (check the backend logs, not the judge). A run full of `wrong` with no `ER` means the pipeline runs but retrieval/generation quality is the problem — see the [Results](../README.md#results) section in the root README for how to read that.

Useful flags:
- `--limit N` — stratified subset (preserves difficulty mix), cheap smoke test.
- `--ids id1,id2` — run explicit questions (assemble a full eval across multiple quota-limited runs).
- `--rejudge path/to/eval_results_*.json` — re-score saved answers with a different judge, without regenerating (no LLM calls for the pipeline, only for the judge).

---

## Known gotchas (found while verifying this guide)

- **`psycopg2`, not `psycopg`** — if you're checking installed packages by hand, the import name is `psycopg2` (`psycopg2-binary` in requirements.txt).
- **`answer_question` is synchronous by design** (`backend/app/rag/pipeline.py`) — every collaborator (embedder, psycopg2, LLM clients) blocks, so it's not an `async def`. `scripts/eval.py` previously awaited it anyway, which threw `'QueryResponse' object can't be awaited` on every single question — that bug is fixed as of this guide (removed the erroneous `await` in `_pipeline_run`). If you see that exact error again on an older checkout, that's why.
- **`openai_compat` requires all three of `LLM_BASE_URL`/`LLM_API_KEY`/`LLM_MODEL`** — partial config raises at `Settings()` import time, before the server even binds a port.
- **First backend boot is slow** — bge-m3 download + load easily takes 10-20s. Don't assume the server is broken if `/health` doesn't answer immediately.
