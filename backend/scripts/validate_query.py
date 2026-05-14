"""
Valida el pipeline de retrieval: embebe una pregunta y consulta pgvector.
Uso: python scripts/validate_query.py "tu pregunta aquí"
"""
import sys
import os
from dotenv import load_dotenv
import psycopg2
from pgvector.psycopg2 import register_vector
from sentence_transformers import SentenceTransformer

load_dotenv()

EMBED_MODEL = "BAAI/bge-m3"
DATABASE_URL = os.getenv("DATABASE_URL")
TOP_K = 5

def main():
    question = " ".join(sys.argv[1:]) if len(sys.argv) > 1 else "How many copies of the same card can I include in my deck?"

    print(f"\nPregunta: {question}\n")

    print("Cargando modelo...")
    model = SentenceTransformer(EMBED_MODEL)
    embedding = model.encode(question, normalize_embeddings=True).tolist()

    print("Conectando a Supabase...")
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)

    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT section, source_type, source_document,
                   LEFT(content, 300) AS preview,
                   1 - (embedding <=> %s::vector) AS similarity
            FROM corpus_chunks
            ORDER BY embedding <=> %s::vector
            LIMIT %s
            """,
            (embedding, embedding, TOP_K),
        )
        rows = cur.fetchall()

    conn.close()

    print(f"\nTop {TOP_K} resultados:\n" + "=" * 60)
    for i, (section, source_type, source_doc, preview, sim) in enumerate(rows, 1):
        print(f"\n[{i}] {section} ({source_type}/{source_doc}) — similitud: {sim:.4f}")
        print(f"    {preview.strip()[:200]}...")

if __name__ == "__main__":
    main()
