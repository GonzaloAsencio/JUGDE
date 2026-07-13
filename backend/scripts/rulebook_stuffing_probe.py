"""Offline probe for plan 4.3: full-rulebook stuffing for hard queries.

Zero product code. For each target question the context is built as:

  [detected card sections from cards.md] + [the ENTIRE rulebook.md as one chunk]

and generation runs through the PRODUCTION prompt path (build_prompt +
_SYSTEM_INSTRUCTION v6, same multi-card scaffold rule, prod temperature and
max_output_tokens) — the only variable vs prod is the context: stuffed instead
of retrieved. This tests whether the 4 residual misses (eval-014/015/017/019,
a vocabulary bridge no retrieval expansion reaches) become answerable when
retrieval failure is eliminated by definition.

Controls: 2 questions that answer correctly today (eval-001, eval-030) to
catch long-context degradation — a win on the misses is worthless if the
giant context breaks what already works.

Sampling: 3 samples per question (judge correct%% has ±10pp variance; per the
plan's Fase-4 criterion, verdicts are majority/hand-read, never single-run).
The deterministic signal printed here is "gold rule code cited in the answer"
(sub-rule coverage, same semantics as eval_judge._rule_codes_cover). Full
answers + usage_metadata + latency go to data/stuffing_probe_<ts>.json for
hand reading against canonical_answer.

The Gemini call duplicates _call_gemini's config instead of calling it because
the probe needs usage_metadata (feasibility: free-tier TPM) and a longer
timeout — a ~75K-token prompt does not fit prod's 30s budget reliably.

Usage (from backend/):
    python -m scripts.rulebook_stuffing_probe [--samples 3] [--pace 25]

Requires GEMINI_API_KEY (Settings). Does NOT need the DB or the judge.
"""
import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from app.config import Settings
from app.rag.generation import _MULTI_CARD_SCAFFOLD, build_prompt, needs_scaffold
from app.rag.pipeline import _KNOWN_KEYWORDS
from app.rag.routing import build_stuffed_chunks
from app.rag.rules import extract_rule_codes
from scripts.eval_judge import _parse_refs, _rule_codes_cover

MISSES = ["eval-014", "eval-015", "eval-017", "eval-019"]
CONTROLS = ["eval-001", "eval-030"]

DATA = Path(__file__).resolve().parent.parent / "data"
REFUSAL = "I don't have enough information to answer that question"


def call_stuffed(client, model: str, prompt: str, *, temperature: float,
                 max_output_tokens: int, timeout_s: float = 120.0):
    """generate_content with _call_gemini's exact config, but returning the raw
    response (usage_metadata) and retrying 429s on a TPM-sized backoff — the
    bounded prod backoff (max ~4s) cannot outlive a per-minute token window."""
    from google.genai import types

    config = types.GenerateContentConfig(
        temperature=temperature,
        max_output_tokens=max_output_tokens,
        http_options=types.HttpOptions(timeout=int(timeout_s * 1000)),
    )
    for attempt in range(3):
        try:
            return client.models.generate_content(model=model, contents=prompt, config=config)
        except Exception as e:
            if "429" not in str(e) and getattr(e, "code", None) != 429:
                raise
            if attempt == 2:
                raise
            print(f"    [429] waiting 65s (attempt {attempt + 1})")
            time.sleep(65)
    raise AssertionError("unreachable")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--pace", type=float, default=25.0,
                    help="seconds between calls (~75K-token prompts vs 250K TPM)")
    ap.add_argument("--ids", nargs="*", default=MISSES + CONTROLS)
    ap.add_argument("--model", default=None,
                    help="override settings.gemini_model (4.2 probe: thinking model)")
    ap.add_argument("--max-out", type=int, default=None,
                    help="override max_output_tokens (thinking models spend the "
                         "output budget on thoughts; 1024 strangles them)")
    args = ap.parse_args()

    s = Settings()
    if not s.gemini_api_key:
        raise SystemExit("GEMINI_API_KEY required (probe uses the gemini provider path).")
    from google import genai
    client = genai.Client(api_key=s.gemini_api_key)
    model = args.model or s.gemini_model
    max_out = args.max_out or s.max_output_tokens

    eval_set = json.loads((DATA / "eval_set.json").read_text(encoding="utf-8"))
    by_id = {q["id"]: q for q in eval_set["questions"]}
    questions = [by_id[qid] for qid in args.ids]

    print(f"model={model}  temp={s.gemini_temperature}  "
          f"max_out={max_out}  samples={args.samples}  pace={args.pace}s")
    print(f"questions: {[q['id'] for q in questions]}\n")

    results = []
    first_call = True
    for q in questions:
        refs = _parse_refs(q.get("rule_reference"))
        # The PRODUCTION stuffed-context builder — the probe certifies the
        # exact context assembly the routed pipeline uses.
        chunks = build_stuffed_chunks(q["question"], known_keywords=_KNOWN_KEYWORDS)
        if chunks is None:
            raise SystemExit("stuffing unavailable: data/processed files missing")
        mentions = [c.section for c in chunks if c.source_type == "card"]
        extra = _MULTI_CARD_SCAFFOLD if needs_scaffold(q["question"], len(mentions)) else ""
        prompt = build_prompt(q["question"], chunks, extra_system=extra)
        kind = "MISS" if q["id"] in MISSES else "CONTROL"
        print(f"{q['id']} [{kind}]  cards={mentions}  refs={refs}  "
              f"prompt={len(prompt):,} chars  scaffold={'on' if extra else 'off'}")

        samples = []
        for i in range(args.samples):
            if not first_call:
                time.sleep(args.pace)
            first_call = False
            t0 = time.monotonic()
            try:
                resp = call_stuffed(client, model, prompt,
                                    temperature=s.gemini_temperature,
                                    max_output_tokens=max_out)
                answer = resp.text or ""
                usage = getattr(resp, "usage_metadata", None)
                usage_d = {
                    "prompt_tokens": getattr(usage, "prompt_token_count", None),
                    "output_tokens": getattr(usage, "candidates_token_count", None),
                    "total_tokens": getattr(usage, "total_token_count", None),
                } if usage else None
            except Exception as e:
                answer, usage_d = f"[ERROR] {e}", None
            latency = time.monotonic() - t0

            codes = extract_rule_codes(answer)
            covered = {ref: _rule_codes_cover(ref, codes) for ref in refs}
            refused = REFUSAL in answer
            samples.append({"answer": answer, "latency_s": round(latency, 1),
                            "usage": usage_d, "gold_covered": covered, "refused": refused})
            cov = " ".join(f"{r}={'Y' if ok else 'n'}" for r, ok in covered.items())
            tok = usage_d["prompt_tokens"] if usage_d else "?"
            print(f"  s{i + 1}: {latency:5.1f}s  in={tok}  "
                  f"{'REFUSED' if refused else cov or '(no refs)'}")

        # Majority per ref across samples — the deterministic headline.
        majority = {
            ref: sum(sm["gold_covered"].get(ref, False) for sm in samples) > args.samples / 2
            for ref in refs
        }
        results.append({"id": q["id"], "kind": kind, "model": model, "question": q["question"],
                        "rule_reference": q.get("rule_reference"),
                        "canonical_answer": q.get("canonical_answer"),
                        "card_mentions": mentions, "prompt_chars": len(prompt),
                        "majority_gold_covered": majority, "samples": samples})
        print(f"  majority: {majority}\n")

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out = DATA / f"stuffing_probe_{ts}.json"
    out.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print("=== summary (majority gold-cited; hand-read answers before any verdict) ===")
    for r in results:
        marks = " ".join(f"{ref}={'YES' if ok else 'no'}"
                         for ref, ok in r["majority_gold_covered"].items())
        print(f"  {r['id']} [{r['kind']}]  {marks}")
    print(f"\nsaved: {out}")


if __name__ == "__main__":
    main()
