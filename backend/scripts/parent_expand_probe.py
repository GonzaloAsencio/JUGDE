"""Probe 3.5 small-to-big (cero código de producto): ¿el gold aparece en los
HERMANOS — chunks que comparten parent_section — de lo que el retrieval real de
v2.2.1 ya trae?

Por pregunta: retrieval real (HyDE + reranker) → hit estricto baseline; después
se expande cada chunk rulebook recuperado a todos sus hermanos por
parent_section y se re-evalúa el hit sobre el conjunto expandido. Reporta
también el costo de la expansión (chunks y ~tokens extra que irían al LLM).
"""
import sys, os

sys.path.insert(0, r"C:\Users\gonch\Documents\GitHub\Judge\backend")
os.chdir(r"C:\Users\gonch\Documents\GitHub\Judge\backend")
from dotenv import load_dotenv
load_dotenv(".env")

from app.config import Settings
from app.db import init_pool, get_conn
from app.rag.embedder import Embedder
from app.rag.pipeline import _retrieve, _build_citations
from app.rag.provider import create_provider
from app.rag.retrieval import Chunk
from scripts.eval import _load_eval_set, stratified_subset
from scripts.eval_judge import match_rule_reference

CV = "v2.2.1"

_SIBLINGS_SQL = """
SELECT id, content, section, parent_section, source_type, metadata
FROM corpus_chunks
WHERE corpus_version = %s AND parent_section = ANY(%s)
"""


class HydeMemo:
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

rescues, regressions = [], []
print(f"{'id':9} {'base':>5} {'expand':>6} {'parents':>7} {'sibs':>5} {'~tok+':>6}")
for q in questions:
    ref = q.get("rule_reference")
    if ref is None:
        continue
    chunks, _, _, _, _ = _retrieve(
        q["question"], embedder, pool, provider, settings,
        None, CV, f"s2b-{q['id']}",
    )
    base = match_rule_reference(ref, _build_citations(chunks))

    parents = sorted({c.parent_section for c in chunks
                      if c.source_type == "rulebook" and c.parent_section})
    seen = {c.id for c in chunks}
    siblings = []
    if parents:
        with get_conn(pool) as conn:
            with conn.cursor() as cur:
                cur.execute(_SIBLINGS_SQL, (CV, parents))
                for r in cur.fetchall():
                    if str(r[0]) not in seen:
                        siblings.append(Chunk(
                            id=str(r[0]), content=r[1], section=r[2],
                            parent_section=r[3], source_type=r[4],
                            similarity=0.0, metadata=r[5],
                        ))
    expanded = match_rule_reference(ref, _build_citations(list(chunks) + siblings))
    extra_tokens = sum(len(s.content) for s in siblings) // 4

    marker = ""
    if not base and expanded:
        marker = " <== RESCUE"
        rescues.append(q["id"])
    print(f"{q['id']:9} {str(base):>5} {str(expanded):>6} {len(parents):>7} "
          f"{len(siblings):>5} {extra_tokens:>6}{marker}")

print(f"\nRESCUES (miss -> hit por expansión): {rescues}")
