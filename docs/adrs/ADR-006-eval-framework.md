# ADR-006 — Eval Framework: LLM-as-Judge over RAGAS

**Status**: Accepted — supersedes the eval framework described in `Specs/03_eval_set_spec.md` and `Specs/06_retrieval_ablation_spec.md`  
**Date**: 2026-06-22  
**Authors**: Gonzalo Asencio

---

## Context

The original plan (`Specs/03`, `Specs/06`) specified [RAGAS](https://github.com/explodinggradients/ragas) as the evaluation framework, reporting four metrics — Faithfulness, Answer Relevancy, Context Precision, and Context Recall — across an ablation of retrieval configurations (A: vector-only, B: hybrid, C: + reranker, D: + entity resolution).

In practice, the project was built in a different order than the roadmap: the RAG pipeline, the frontend, and production hardening landed first, and the evaluation harness was prioritized last. By the time it was implemented, what was needed was a fast, dependency-light way to get *some* measured signal on answer quality — not a full RAGAS integration.

The harness lives in `backend/scripts/eval.py` and `backend/scripts/eval_judge.py`, isolated from the production pipeline.

---

## Decision

Implement a self-contained **LLM-as-judge** harness instead of integrating RAGAS for v1.

- **Answer quality**: an LLM judge (`judge_answer`) compares the generated answer against the `canonical_answer` and returns a verdict of `correct`, `partial`, or `wrong`.
- **Retrieval recall**: computed deterministically (`match_rule_reference`) by checking whether the expected `rule_reference` appears in the returned citations (section prefix, content match, or errata source).

The judge reuses the existing `LLMProvider` abstraction and runs against Gemini (or any OpenAI-compatible endpoint via `JUDGE_*`/`LLM_*` env vars).

---

## Alternatives Considered

| Option | Reason rejected (for v1) |
|---|---|
| **RAGAS** | More integration work and a heavier dependency tree. Evaluation was the last-prioritized piece; the goal was a measured baseline quickly, not the most granular metrics. Its strongest unique metric — faithfulness — is partially mitigated by behaviour today (see Consequences). Kept as optional future work. |
| **Manual human grading** | Not repeatable or automatable; does not scale as the eval set grows. |
| **Exact-string / regex match against `canonical_answer`** | Too brittle for natural-language answers — penalizes correct paraphrases and rewards superficial overlap. |

---

## Consequences

✅ Zero new dependencies — the judge reuses the existing provider; no RAGAS install or version pinning.  
✅ Full control of the judge prompt — verdict criteria are explicit and tunable in `eval_judge.py`.  
✅ Deterministic retrieval recall — the recall number is reproducible run-to-run, unlike the LLM verdicts.  
✅ A measured baseline exists — ~25% correct (35% correct+partial), 14% retrieval recall — enough to drive the next decisions.  

❌ Coarser than RAGAS — a single correct/partial/wrong verdict does not separate retrieval failures from generation failures the way RAGAS's four metrics do.  
❌ **No faithfulness metric** — the harness does not measure whether an answer is grounded in the corpus versus the model's own knowledge. This is the metric most aligned with the project's "never invent rules" promise. Today the risk is mitigated by behaviour (grounding-forced system prompt, `post_gen_validate` stripping hallucinated citations, `query.no_info_despite_context` logging) but it is not measured. Adding RAGAS later would close this gap — tracked in `FUTURE_WORK.md`.  
❌ Non-deterministic verdicts — the LLM judge can return different verdicts across runs, so answer-quality numbers carry run-to-run noise.
