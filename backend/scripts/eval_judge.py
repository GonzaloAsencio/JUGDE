"""LLM-as-judge for the eval harness.

Isolated from the production pipeline. Configurable via env:
  JUDGE_BASE_URL, JUDGE_API_KEY, JUDGE_MODEL  → OpenAI-compat endpoint
  (if absent → falls back to Gemini using GEMINI_API_KEY)
"""
import json
import os
import re


_JUDGE_PROMPT = """\
You are an impartial evaluator for a rules Q&A system about the Riftbound trading card game.

Given:
- QUESTION: the user's rules question
- CANONICAL ANSWER: the authoritative correct answer
- GENERATED ANSWER: the system's response to evaluate

Evaluate whether the generated answer is correct, partially correct, or wrong.

Criteria:
- correct: captures all key information from the canonical answer without contradictions.
- partial: contains some correct information but is incomplete, vague, or has minor inaccuracies.
- wrong: contradicts the canonical answer or provides clearly incorrect information.

Respond with ONLY a JSON object, nothing else:
{{"verdict": "correct|partial|wrong", "justification": "1-2 sentence explanation"}}

QUESTION: {question}

CANONICAL ANSWER: {canonical_answer}

GENERATED ANSWER: {generated_answer}
"""


# ---------------------------------------------------------------------------
# Verdict parsing (pure — testable without network)
# ---------------------------------------------------------------------------

def parse_verdict(raw: str) -> dict:
    """Parse LLM response into {verdict, justification}. Returns error on failure."""
    if not raw:
        return {"verdict": "error", "justification": "Empty response from judge"}

    match = re.search(r'\{[^{}]*"verdict"[^{}]*\}', raw, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group())
            verdict = str(data.get("verdict", "")).lower()
            if verdict in ("correct", "partial", "wrong"):
                return {
                    "verdict": verdict,
                    "justification": str(data.get("justification", ""))[:500],
                }
        except json.JSONDecodeError:
            pass

    return {"verdict": "error", "justification": f"Could not parse verdict from: {raw[:100]}"}


# ---------------------------------------------------------------------------
# Retrieval matching (pure — testable without network)
# ---------------------------------------------------------------------------

def _parse_refs(rule_reference: str | None) -> list[str]:
    if not rule_reference:
        return []
    return [r.strip() for r in rule_reference.split(",") if r.strip()]


def _numeric_prefix(ref: str) -> str | None:
    m = re.match(r"^(\d+)", ref)
    return m.group(1) if m else None


def _section_matches_prefix(section: str, prefix: str) -> bool:
    s = section.strip()
    return s == prefix or s.startswith(prefix + ".") or s.startswith(prefix + " ")


def _sub_prefix(ref: str) -> str | None:
    """Return the second-level prefix, e.g. '103.2.b' → '103.2'. None if no dot."""
    parts = ref.split(".")
    return f"{parts[0]}.{parts[1]}" if len(parts) >= 2 else None


def _rule_codes_cover(ref: str, codes) -> bool:
    """True if any rule code shares *ref*'s numeric lineage.

    A chunk covers the ref when it lists the exact rule, a sub-rule of it
    (``103`` covers ``103.2``), or its parent (``103.2`` covers ``103.2.b``).
    """
    for code in codes:
        if code == ref or code.startswith(ref + ".") or ref.startswith(code + "."):
            return True
    return False


def _single_ref_hit(ref: str, citations) -> bool:
    if ref.startswith("errata/"):
        return any(c.source_type == "errata" for c in citations)

    # Primary: structured rule-code lineage. Derived from each chunk's FULL
    # content at query time, so it doesn't depend on the section header number
    # or on the rule landing inside the 200-char preview.
    for c in citations:
        if _rule_codes_cover(ref, getattr(c, "rule_codes", None) or []):
            return True

    # Fallback (legacy): section prefix + content_preview. Kept for citations
    # that predate rule_codes or carry no codes.
    prefix = _numeric_prefix(ref)
    sub = _sub_prefix(ref)

    for c in citations:
        if prefix and _section_matches_prefix(c.section, prefix):
            return True
        preview = c.content_preview
        if ref in preview:
            return True
        if sub and sub in preview:
            return True

    return False


def match_rule_reference(rule_reference: str | None, citations) -> bool:
    """Return True if citations contain evidence of the given rule_reference.

    Handles: numeric prefixes (103.2.b → section '103.'), content_preview matches,
    errata path refs (errata/...), multi-refs (comma-separated), and nulls.
    """
    refs = _parse_refs(rule_reference)
    if not refs:
        return False
    return any(_single_ref_hit(ref, citations) for ref in refs)


# ---------------------------------------------------------------------------
# Aggregation helpers (pure — testable without network)
# ---------------------------------------------------------------------------

def compute_recall(results: list[dict]) -> dict:
    """Compute retrieval recall from a list of per-question result dicts."""
    evaluable = [r for r in results if r["has_ref"]]
    hits = sum(1 for r in evaluable if r["retrieval_hit"])
    return {
        "hits": hits,
        "evaluable": len(evaluable),
        "null_ref": len(results) - len(evaluable),
        "recall": hits / len(evaluable) if evaluable else 0.0,
    }


def aggregate_by_difficulty(results: list[dict]) -> dict:
    """Group verdict counts by difficulty level."""
    groups: dict = {}
    for r in results:
        d = r.get("difficulty", "unknown")
        if d not in groups:
            groups[d] = {"correct": 0, "partial": 0, "wrong": 0, "error": 0, "total": 0}
        verdict = r.get("verdict", "error")
        groups[d][verdict] = groups[d].get(verdict, 0) + 1
        groups[d]["total"] += 1
    return groups


def aggregate_by_source(results: list[dict]) -> dict:
    """Group verdict counts by source (rulebook/errata/faq/etc.)."""
    groups: dict = {}
    for r in results:
        s = r.get("source", "unknown")
        if s not in groups:
            groups[s] = {"correct": 0, "partial": 0, "wrong": 0, "error": 0, "total": 0}
        verdict = r.get("verdict", "error")
        groups[s][verdict] = groups[s].get(verdict, 0) + 1
        groups[s]["total"] += 1
    return groups


# ---------------------------------------------------------------------------
# LLM judge (network — not unit-tested directly)
# ---------------------------------------------------------------------------

def _get_judge_config() -> dict | None:
    """Return OpenAI-compat config for the judge.

    Priority: JUDGE_* vars (dedicated judge endpoint) > LLM_* vars (pipeline fallback).
    NOTE: Falling back to LLM_* shares rate-limit quota with the pipeline.
    Set JUDGE_BASE_URL/JUDGE_API_KEY/JUDGE_MODEL to a separate endpoint to avoid this.
    If neither JUDGE_* nor LLM_* are set, falls back to Gemini via GEMINI_API_KEY.
    Set JUDGE_PROVIDER=gemini to force the Gemini judge even when LLM_* are set
    (needed to run local generation + Gemini judge without exposing the API key).
    """
    if os.getenv("JUDGE_PROVIDER", "").lower() == "gemini":
        return None
    base_url = os.getenv("JUDGE_BASE_URL") or os.getenv("LLM_BASE_URL")
    api_key = os.getenv("JUDGE_API_KEY") or os.getenv("LLM_API_KEY")
    model = os.getenv("JUDGE_MODEL") or os.getenv("LLM_MODEL")
    if base_url and api_key and model:
        return {"base_url": base_url, "api_key": api_key, "model": model}
    return None


def _judge_timeout_s() -> float:
    """Judge call timeout in seconds.

    JUDGE_TIMEOUT_S wins; else reuse GEMINI_TIMEOUT_S (the local-LLM knob); else 30s.
    A slow local judge needs the same headroom as generation — otherwise verdicts
    come back as timeout errors even though the answer was generated fine.
    """
    return float(os.getenv("JUDGE_TIMEOUT_S") or os.getenv("GEMINI_TIMEOUT_S") or 30.0)


def _judge_openai_compat(prompt: str, config: dict) -> str:
    import openai

    from app.rag.generation import _completion_with_retry

    client = openai.OpenAI(base_url=config["base_url"], api_key=config["api_key"])
    response = _completion_with_retry(lambda: client.chat.completions.create(
        model=config["model"],
        messages=[{"role": "user", "content": prompt}],
        temperature=0.0,
        timeout=_judge_timeout_s(),
    ))
    return response.choices[0].message.content or ""


def _judge_gemini(prompt: str) -> str:
    from google import genai
    from app.rag.generation import _call_gemini

    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set and no JUDGE_* env vars configured")
    client = genai.Client(api_key=api_key)
    model = os.getenv("JUDGE_GEMINI_MODEL", "gemini-2.0-flash")
    return _call_gemini(client, model, prompt, temperature=0.0, timeout_s=30.0)


def judge_answer(question: str, canonical_answer: str, generated_answer: str) -> dict:
    """Judge a generated answer against the canonical answer.

    Returns {"verdict": correct|partial|wrong|error, "justification": str}.
    Never raises — errors are captured as verdict="error".
    """
    prompt = _JUDGE_PROMPT.format(
        question=question,
        canonical_answer=canonical_answer,
        generated_answer=generated_answer,
    )
    try:
        config = _get_judge_config()
        if config:
            raw = _judge_openai_compat(prompt, config)
        else:
            raw = _judge_gemini(prompt)
        return parse_verdict(raw)
    except Exception as e:
        return {"verdict": "error", "justification": str(e)[:200]}
