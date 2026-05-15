# ADR-005 — LLM Choice: Gemini 2.0 Flash over GPT-4o-mini and Claude Haiku

**Status**: Accepted  
**Date**: 2026-05-15  
**Authors**: Gonzalo Asencio

---

## Context

The RAG pipeline requires an LLM for the generation step: given a user question and a set of retrieved rulebook chunks, produce a grounded answer with citation references. The model must follow structured instructions reliably (system prompt with grounding rules, citation formatting), handle a context window of roughly 2000–4000 tokens per request, and be available at low or zero cost during development.

The application uses `gemini_model: str = "gemini-2.0-flash"` as configured in `backend/app/config.py`. The LLM call is isolated in `backend/app/rag/generation.py` so the model can be swapped without touching the pipeline.

Candidates evaluated:
- `gemini-2.0-flash` (Google AI Studio free tier)
- `gpt-4o-mini` (OpenAI API, paid)
- `claude-3-haiku-20240307` (Anthropic API, paid)
- Self-hosted Llama 3 (local inference)

---

## Decision

Use `gemini-2.0-flash` via the Google AI Studio API (`google-generativeai` SDK).

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| `gpt-4o-mini` | Paid — every request incurs cost. Not viable for a free-tier side project with open demo access. |
| `claude-3-haiku-20240307` | Also paid. Anthropic does not offer a meaningful free tier for production traffic. |
| Self-hosted Llama 3 | Requires GPU infrastructure or CPU inference with high latency (~15–30s per request). Operational overhead of running a model server is disproportionate for this project scope. |
| `gemini-2.5-flash` (thinking mode) | Evaluated informally — thinking mode introduces ~15 second latency per request, which is unacceptable for an interactive Q&A interface. The quality improvement for rule-grounded answers did not justify the latency cost. |

---

## Consequences

✅ Free tier — Google AI Studio provides 1 million tokens per day on gemini-2.0-flash at no cost, sufficient for development and demo traffic.  
✅ Fast generation — gemini-2.0-flash returns answers in under 3 seconds for typical prompt sizes, keeping end-to-end latency reasonable.  
✅ Good instruction following — the model reliably respects the grounding prompt (cite only provided context, do not hallucinate rule text, defer to judge when uncertain).  
✅ Model is isolated — `backend/app/rag/generation.py` owns the Gemini call; swapping the model requires changing one function, not the pipeline.  

❌ Vendor lock-in — Google can change the free tier limits, deprecate model versions, or introduce breaking API changes. Mitigated by the isolation boundary but not eliminated.  
❌ Rate limit hit in production — the 1M token/day free tier is hit under sustained demo traffic, requiring backoff logic and graceful degradation.  
❌ No SLA on free tier — latency and availability are not guaranteed, which is acceptable for a portfolio project but would require a paid plan in production.
