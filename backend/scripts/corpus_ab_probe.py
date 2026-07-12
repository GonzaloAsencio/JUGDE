"""Retrieval-only A/B: two corpus versions (OLD vs NEW), per-question, paired HyDE.

Same 20-question stratified subset (seed 42) the eval harness uses. Zero
generation, zero judge — the only LLM calls are HyDE, memoized per question so
both corpus arms see the IDENTICAL HyDE text (kills the flakiness confound
discovered on 2026-07-11).
"""
import sys, os

sys.path.insert(0, r"C:\Users\gonch\Documents\GitHub\Judge\backend")
os.chdir(r"C:\Users\gonch\Documents\GitHub\Judge\backend")
from dotenv import load_dotenv
load_dotenv(".env")

import json

from app.config import Settings
from app.db import init_pool, get_conn
from app.rag.embedder import Embedder
from app.rag.pipeline import _retrieve, _build_citations
from app.rag.provider import create_provider
from scripts.eval import _load_eval_set, stratified_subset
from scripts.eval_judge import match_rule_reference

OLD, NEW = "v2.2.1", "v2.3.1"


class HydeMemo:
    """Provider wrapper: memoize hyde per question so both arms pair exactly."""
    def __init__(self, inner):
        self._inner = inner
        self._memo = {}

    def hyde(self, question: str) -> str:
        if question not in self._memo:
            self._memo[question] = self._inner.hyde(question)
        return self._memo[question]

    def __getattr__(self, name):
        return getattr(self._inner, name)


settings = Settings()
pool = init_pool(settings.database_url, settings.db_pool_min, settings.db_pool_max)
embedder = Embedder.load(settings.model_name)
llm_client = None
if settings.llm_provider == "gemini":
    from google import genai
    llm_client = genai.Client(api_key=settings.gemini_api_key)
provider = HydeMemo(create_provider(settings, llm_client))

questions = stratified_subset(_load_eval_set(), 20, seed=42)

wins, losses = [], []
print(f"{'id':9} {'old':>4} {'new':>4}  hyde")
for q in questions:
    ref = q.get("rule_reference")
    if ref is None:
        continue
    hits = {}
    for cv in (OLD, NEW):
        chunks, _, _, _, _ = _retrieve(
            q["question"], embedder, pool, provider, settings,
            None, cv, f"ab-{q['id']}-{cv}",
        )
        hits[cv] = match_rule_reference(ref, _build_citations(chunks))
    hyde_ok = "y" if provider._memo.get(q["question"]) else "EMPTY"
    marker = ""
    if hits[OLD] != hits[NEW]:
        marker = " <== WIN" if hits[NEW] else " <== LOSS"
        (wins if hits[NEW] else losses).append(q["id"])
    print(f"{q['id']:9} {str(hits[OLD]):>4} {str(hits[NEW]):>4}  {hyde_ok}{marker}")

print(f"\nWINS: {wins}")
print(f"LOSSES: {losses}")
