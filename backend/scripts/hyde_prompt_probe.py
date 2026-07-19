"""GATE 3.14 — HyDE-writer prompt v2: does a rulebook-voice passage bridge the
vocabulary gap of the class-B misses?

The mechanism, read from the corpus (plan §3.14): eval-037's question says
"Defy" / "Power cost"; its gold rules say "Counter" (425) and "printed cost"
(131.4). The current HyDE passage repeats the question's vocabulary; these
variants make the writer translate card keywords into the rulebook's FORMAL
terms — the exact bridge the class-B gaps need.

Pre-committed rule (docs/improvement-plan.md §3.14, committed BEFORE running):
a variant LIVES iff it covers >=1 of eval-037's target refs (131.4, 425) that
the control arm misses, CONFIRMED by a re-run (passages are sampled), AND has
ZERO persistent coverage regressions across the whole non-routed universe
(loss confirmed by re-run kills — the 2.2 standard). 383.3.d (eval-020) is
reported as information only and never gates.

The arm's prompt is injected by patching generation._HYDE_PROMPT so the code
path stays byte-identical to production; both arms write with the PROD writer
(gemma-4-31b, the 2.2 flip) regardless of the local .env.

Cost: ~3 hyde calls per question (plus confirmations), ZERO Gemini, zero judge.

Usage (from backend/):
    python -m scripts.hyde_prompt_probe
"""
import json
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

import app.rag.generation as generation
from app.config import Settings
from app.db import close_pool, init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import _retrieve
from app.rag.provider import OpenAICompatProvider
from scripts.eval_judge import _parse_refs
from scripts.hyde_model_probe import _load_universe, regressions
from scripts.retrieval_probe import _resolve_corpus_version, per_ref_ranks

_EVAL_SET = Path(__file__).parent.parent / "data" / "eval_set.json"

# The PROD HyDE writer (2.2 flip, verified via /health). Hardcoded so a local
# .env without HYDE_MODEL still measures what production runs.
PROD_HYDE_WRITER = "gemma-4-31b"

TARGET_ID = "eval-037"
TARGET_REFS = frozenset({"131.4", "425"})
INFO_ID = "eval-020"
INFO_REF = "383.3.d"

V_RULEBOOK = """\
You write excerpts of the official rulebook of the Riftbound trading card game.
Write a short passage (2-4 sentences) of formal rules text that would resolve
the question below. Use the rulebook's formal voice and defined terminology —
the general game actions and defined terms, not the question's conversational
wording. It does not need to be perfectly correct — it will be used to retrieve
the real rule by semantic similarity. Output only the passage.

Question: {question}
Passage:"""

V_TERMS = """\
You answer rules questions about the Riftbound trading card game.
First, name the GENERAL game mechanics involved in the question below —
translate any card-specific keyword into the generic game action it performs
(the formal term a rulebook would use for it). Then write a short, confident
hypothetical answer (2-3 sentences) using those formal terms. It does not need
to be perfectly correct — it will be used to retrieve the real rule by semantic
similarity. Output only the mechanics list and the answer.

Question: {question}
Answer:"""

VARIANTS = {"v-rulebook": V_RULEBOOK, "v-terms": V_TERMS}


# ---------------------------------------------------------------------------
# Pure logic (unit-tested in tests/test_hyde_prompt_probe.py)
# ---------------------------------------------------------------------------

def variant_lives(confirmed_target_wins: frozenset, persistent_regressions: bool) -> bool:
    """The pre-committed rule: >=1 confirmed target win AND zero persistent
    regressions anywhere in the universe."""
    return bool(confirmed_target_wins) and not persistent_regressions


# ---------------------------------------------------------------------------
# DB/LLM-driven probe (manual run — not unit-tested)
# ---------------------------------------------------------------------------

@contextmanager
def _hyde_prompt(template: str | None):
    """Swap generation._HYDE_PROMPT for one arm; None = production prompt."""
    if template is None:
        yield
        return
    original = generation._HYDE_PROMPT
    generation._HYDE_PROMPT = template
    try:
        yield
    finally:
        generation._HYDE_PROMPT = original


@dataclass(frozen=True)
class Arm:
    covered: frozenset
    latency_s: float


def _run_arm(question, refs, template, provider, embedder, pool, settings, corpus_version) -> Arm:
    t0 = time.time()
    with _hyde_prompt(template):
        chunks, _, _, _, _ = _retrieve(
            question, embedder, pool, provider, settings, None, corpus_version,
            "hyde-prompt-probe", skip_hyde=False,
        )
    covered = frozenset(
        ref for ref, rank in per_ref_ranks(list(refs), chunks).items() if rank is not None
    )
    return Arm(covered=covered, latency_s=time.time() - t0)


def main() -> None:
    settings = Settings()
    if settings.llm_provider != "openai_compat":
        sys.exit("This gate mirrors prod: set LLM_PROVIDER=openai_compat.")

    pool = init_pool(settings.database_url, minconn=1, maxconn=3)
    corpus_version = _resolve_corpus_version(pool, settings)
    provider = OpenAICompatProvider(
        base_url=settings.llm_base_url,
        api_key=settings.llm_api_key,
        model=settings.llm_model,
        temperature=settings.gemini_temperature,
        timeout_s=settings.gemini_timeout_s,
        max_output_tokens=settings.max_output_tokens,
        hyde_model=PROD_HYDE_WRITER,
    )
    print(f"  corpus_version = {corpus_version} | hyde writer = {provider.hyde_model}")

    print("Loading embedder (~5-10s)...")
    embedder = Embedder.load(settings.model_name)

    report: dict[str, dict] = {name: {"regressions": [], "target_wins": frozenset()}
                               for name in VARIANTS}
    try:
        universe = _load_universe(pool, corpus_version)
        print(f"  universe: {len(universe)} non-routed evaluable questions\n")

        for q in universe:
            qid = q.get("id", "?")
            refs = tuple(_parse_refs(q["rule_reference"]))
            control = _run_arm(q["question"], refs, None, provider,
                               embedder, pool, settings, corpus_version)
            line = f"    {qid:10s} control={len(control.covered)}/{len(refs)}"
            for name, template in VARIANTS.items():
                arm = _run_arm(q["question"], refs, template, provider,
                               embedder, pool, settings, corpus_version)
                lost = regressions(control.covered, arm.covered)
                persistent = frozenset()
                if lost:
                    retry = _run_arm(q["question"], refs, template, provider,
                                     embedder, pool, settings, corpus_version)
                    persistent = lost & regressions(control.covered, retry.covered)
                    if persistent:
                        report[name]["regressions"].append((qid, sorted(persistent)))
                wins = arm.covered - control.covered
                confirmed_wins = frozenset()
                if qid == TARGET_ID and (wins & TARGET_REFS):
                    # A sampled one-off is not evidence in either direction:
                    # a target win must persist on a fresh passage too.
                    retry = _run_arm(q["question"], refs, template, provider,
                                     embedder, pool, settings, corpus_version)
                    confirmed_wins = (wins & TARGET_REFS) & (retry.covered - control.covered)
                    report[name]["target_wins"] = report[name]["target_wins"] | confirmed_wins
                marks = []
                if persistent:
                    marks.append(f"REGRESSION {sorted(persistent)}")
                elif lost:
                    marks.append("transient-loss")
                if wins:
                    marks.append(f"win {sorted(wins)}" + (" CONFIRMED" if confirmed_wins else ""))
                line += f" | {name}={len(arm.covered)}/{len(refs)} {' '.join(marks)}"
            print(line)
    finally:
        close_pool(pool)

    print("\n" + "=" * 64)
    print("HYDE PROMPT V2 GATE (plan §3.14)")
    print("=" * 64)
    for name in VARIANTS:
        r = report[name]
        lives = variant_lives(r["target_wins"], bool(r["regressions"]))
        print(f"  {name}:")
        print(f"    confirmed target wins ({TARGET_ID}): {sorted(r['target_wins']) or 'none'}")
        print(f"    persistent regressions: {r['regressions'] or 'none'}")
        print(f"    VERDICT: {'LIVES' if lives else 'DIES'}")
    print("=" * 64)


if __name__ == "__main__":
    main()
