"""
Migración de corpus v1.1.0 → v1.2.0 para chunks no-rulebook.

Copia errata, tournament_rules y patch_notes desde v1.1.0.
El rulebook se re-ingestea por separado con el parser re-chunkeado.
"""
from dotenv import load_dotenv

load_dotenv()

import os

import psycopg2

conn = psycopg2.connect(os.getenv("DATABASE_URL"))
cur = conn.cursor()
cur.execute("""
    INSERT INTO corpus_chunks
        (id, content, embedding, source_type, source_document,
         section, parent_section, corpus_version, ingested_at)
    SELECT
        id, content, embedding, source_type, source_document,
        section, parent_section, 'v1.2.0', NOW()
    FROM corpus_chunks
    WHERE corpus_version = 'v1.1.0'
      AND source_type != 'rulebook'
    ON CONFLICT (id) DO NOTHING
""")
conn.commit()
print(f"Copiados: {cur.rowcount} chunks no-rulebook a v1.2.0")
conn.close()
