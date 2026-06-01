"""Verifica recall de HNSW vs scan exacto forzado (ground-truth) por versión.
Solo lectura. Carga el modelo una vez.
Uso: python -m scripts.recall_probe
"""
import os
import psycopg2
from pgvector.psycopg2 import register_vector
from dotenv import load_dotenv

from app.rag.embedder import Embedder
from app.rag.retrieval import _SQL

load_dotenv()
SQL = _SQL.format(set_clause="")
K = 5

QUERIES = [
    "How many copies of the same card can I include in my deck?",
    "What happens when two triggered abilities resolve at the same time?",
    "How does combat damage work between units?",
    "Can I play a card during my opponent's turn?",
    "What is the rune cost and how do I pay it?",
    "How does the accelerate keyword work?",
    "What happens when a unit dies in combat?",
    "How do I win the game?",
    "Rules for mulligan and starting hand",
    "How does the champion ability activate?",
]


def ids(conn, emb, version, exact=False):
    with conn.cursor() as cur:
        if exact:
            # fuerza scan secuencial -> top-K exacto (ground truth)
            cur.execute("SET LOCAL enable_indexscan = off")
            cur.execute("SET LOCAL enable_bitmapscan = off")
        cur.execute(SQL, (emb, version, emb, K))
        return [str(r[0]) for r in cur.fetchall()]


def main():
    conn = psycopg2.connect(os.getenv("DATABASE_URL"))
    register_vector(conn)
    model = Embedder.load()

    for version in ("v1.3.0", "v2.0.0"):
        recalls, empties = [], 0
        for q in QUERIES:
            e = model.encode(q)
            truth = ids(conn, e, version, exact=True)
            hnsw = ids(conn, e, version, exact=False)
            conn.rollback()  # limpia los SET LOCAL
            if not hnsw:
                empties += 1
            if truth:
                recalls.append(len(set(hnsw) & set(truth)) / len(truth))
        avg = sum(recalls) / len(recalls) if recalls else 0.0
        print(f"\n=== {version} ===")
        print(f"  recall@{K} (HNSW vs exacto): {avg:.0%}")
        print(f"  queries con 0 resultados: {empties}/{len(QUERIES)}")

    conn.close()
    print("\nOK recall_probe HNSW")


if __name__ == "__main__":
    main()
