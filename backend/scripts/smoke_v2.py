"""Smoke local de v2.0.0: ejercita el código REAL de retrieval (pasos 7-8).

Solo lectura. No escribe nada. Carga el modelo una vez y corre varias queries
contra corpus_version=v2.0.0: hybrid_search, set_filter y tagged_lookup.
Uso: python -m scripts.smoke_v2
"""
import os
from dotenv import load_dotenv

from app.db import init_pool
from app.rag.embedder import Embedder
from app.rag.retrieval import hybrid_search, tagged_lookup

load_dotenv()
VERSION = "v2.0.0"


def show(title, chunks):
    print(f"\n{title}")
    print("-" * 70)
    for i, c in enumerate(chunks[:5], 1):
        s = (c.metadata or {}).get("set")
        print(f"[{i}] set={s!r:14} type={c.source_type:16} sim={c.similarity:.3f} | {c.section[:40]}")


def main():
    pool = init_pool(os.getenv("DATABASE_URL"))
    emb = Embedder.load()

    # 1) Query general de reglas — sin filtro
    q1 = "How many copies of the same card can I include in my deck?"
    e1 = emb.encode(q1)
    show(f"Q1 (sin filtro): {q1}", hybrid_search(pool, e1, q1, VERSION, top_k=5))

    # 2) Misma query con set_filter=origins (debe traer solo origins + core)
    res2 = hybrid_search(pool, e1, q1, VERSION, top_k=5, set_filter="origins")
    show("Q1 + set_filter='origins' (esperado: solo origins/core)", res2)
    bad = [c for c in res2 if (c.metadata or {}).get("set") not in ("origins", "core")]
    print(f"  -> fuera de origins/core: {len(bad)} (esperado 0)")

    # 3) Query de interacción de carta — tagged_lookup
    res3 = tagged_lookup(pool, ["yasuo"], VERSION)
    show("Q3 tagged_lookup(['yasuo'])", res3)

    # 4) Query de errata por expansión
    q4 = "errata spiritforged card text change"
    e4 = emb.encode(q4)
    show(f"Q4: {q4}", hybrid_search(pool, e4, q4, VERSION, top_k=5))

    print("\nOK smoke v2.0.0")


if __name__ == "__main__":
    main()
