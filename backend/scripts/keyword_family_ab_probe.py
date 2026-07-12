"""Retrieval-only A/B del flag 3.5 (keyword family completion), paired HyDE.

Mismo corpus (v2.2.1), mismo subset estratificado (seed 42), HyDE memoizado
por pregunta: el único delta entre brazos es keyword_family_extra 0 vs 8.
Cero generación, cero judge — matcher estricto sobre las citations.
"""
import sys, os

sys.path.insert(0, r"C:\Users\gonch\Documents\GitHub\Judge\backend")
os.chdir(r"C:\Users\gonch\Documents\GitHub\Judge\backend")
from dotenv import load_dotenv
load_dotenv(".env")

from app.config import Settings
from app.db import init_pool
from app.rag.embedder import Embedder
from app.rag.pipeline import _retrieve, _build_citations
from app.rag.provider import create_provider
from scripts.eval import _load_eval_set, stratified_subset
from scripts.eval_judge import match_rule_reference

CV = "v2.2.1"
OFF, ON = 0, 8


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


base_settings = Settings()
pool = init_pool(base_settings.database_url, base_settings.db_pool_min, base_settings.db_pool_max)
embedder = Embedder.load(base_settings.model_name)
llm_client = None
if base_settings.llm_provider == "gemini":
    from google import genai
    llm_client = genai.Client(api_key=base_settings.gemini_api_key)
provider = HydeMemo(create_provider(base_settings, llm_client))

arms = {
    OFF: base_settings.model_copy(update={"keyword_family_extra": OFF}),
    ON: base_settings.model_copy(update={"keyword_family_extra": ON}),
}

questions = stratified_subset(_load_eval_set(), 20, seed=42)

wins, losses = [], []
print(f"{'id':9} {'off':>4} {'on':>4} {'extra':>5}  hyde")
for q in questions:
    ref = q.get("rule_reference")
    if ref is None:
        continue
    hits, n_chunks = {}, {}
    for extra, settings in arms.items():
        chunks, _, _, _, _ = _retrieve(
            q["question"], embedder, pool, provider, settings,
            None, CV, f"kwfam-{q['id']}-{extra}",
        )
        hits[extra] = match_rule_reference(ref, _build_citations(chunks))
        n_chunks[extra] = len(chunks)
    hyde_ok = "y" if provider._memo.get(q["question"]) else "EMPTY"
    marker = ""
    if hits[OFF] != hits[ON]:
        marker = " <== WIN" if hits[ON] else " <== LOSS"
        (wins if hits[ON] else losses).append(q["id"])
    print(f"{q['id']:9} {str(hits[OFF]):>4} {str(hits[ON]):>4} "
          f"{n_chunks[ON] - n_chunks[OFF]:>5}  {hyde_ok}{marker}")

print(f"\nWINS: {wins}")
print(f"LOSSES: {losses}")
