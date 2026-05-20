"""
Pipeline de ingest: Markdown procesado → chunks → embeddings → pgvector

Modos:
  --dry-run : muestra qué haría, no escribe a BD
  --fresh   : borra todos los chunks y re-inserta todo
  --update  : solo inserta chunks nuevos (detecta por hash de contenido)
"""
import argparse
import hashlib
import os
import re
import sys
import time
import uuid
from pathlib import Path

import psycopg2
from dotenv import load_dotenv
from pgvector.psycopg2 import register_vector

load_dotenv()

CORPUS_VERSION = os.getenv("CORPUS_VERSION", "v1.0.0")
DATABASE_URL = os.getenv("DATABASE_URL")
EMBED_MODEL = "BAAI/bge-m3"
CHUNK_SIZE = 512   # tokens aproximados
CHUNK_OVERLAP = 50
_RULE_SPLIT = re.compile(r"(?=\b\d{3,}\.\s)")

SOURCES = [
    ("data/processed/rulebook.md", "rulebook"),
    ("data/processed/errata.md", "errata"),
    ("data/processed/tournament_rules.md", "tournament_rules"),
    ("data/processed/patch_notes.md", "patch_notes"),
]


# ---------------------------------------------------------------------------
# Chunking
# ---------------------------------------------------------------------------

def _approx_tokens(text: str) -> int:
    return len(text) // 4  # 4 chars ≈ 1 token (estimación conservadora)


def _split_into_sections(markdown: str) -> list[dict]:
    """Divide el Markdown en secciones respetando headers H1/H2/H3."""
    pattern = re.compile(r"^(#{1,3})\s+(.+)$", re.MULTILINE)
    matches = list(pattern.finditer(markdown))

    sections = []
    for i, match in enumerate(matches):
        start = match.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(markdown)
        level = len(match.group(1))
        header = match.group(2).strip()
        content = markdown[start:end].strip()
        sections.append({"header": header, "level": level, "content": content})

    return sections


def _chunk_section(section: dict, source_type: str, source_document: str) -> list[dict]:
    """Genera chunks de una sección. Si cabe en CHUNK_SIZE → 1 chunk. Si no → divide con overlap."""
    content = section["content"]
    header = section["header"]
    parent = f"Level {section['level']} — {header}"

    if _approx_tokens(content) <= CHUNK_SIZE:
        return [_make_chunk(content, header, parent, source_type, source_document)]

    # Dividir en párrafos y agrupar respetando el tamaño
    paragraphs = [p.strip() for p in content.split("\n\n") if p.strip()]

    # Fallback: si sigue siendo 1 párrafo gigante, dividir por número de regla (NNN.)
    if len(paragraphs) <= 1 and _approx_tokens(content) > CHUNK_SIZE:
        paragraphs = [p.strip() for p in _RULE_SPLIT.split(content) if p.strip()]
    chunks = []
    current: list[str] = []
    current_tokens = 0

    for para in paragraphs:
        para_tokens = _approx_tokens(para)
        if current_tokens + para_tokens > CHUNK_SIZE and current:
            chunks.append(_make_chunk("\n\n".join(current), header, parent, source_type, source_document))
            # Overlap: retener el último párrafo
            current = current[-1:] if current else []
            current_tokens = _approx_tokens(current[0]) if current else 0
        current.append(para)
        current_tokens += para_tokens

    if current:
        chunks.append(_make_chunk("\n\n".join(current), header, parent, source_type, source_document))

    return chunks


_CHUNK_NAMESPACE = uuid.UUID("a1b2c3d4-e5f6-7890-abcd-ef1234567890")


def _make_chunk(content: str, section: str, parent_section: str, source_type: str, source_document: str) -> dict:
    chunk_id = str(uuid.uuid5(_CHUNK_NAMESPACE, f"{source_document}:{content}"))
    return {
        "id": chunk_id,
        "content": content,
        "source_type": source_type,
        "source_document": source_document,
        "section": section,
        "parent_section": parent_section,
        "corpus_version": CORPUS_VERSION,
    }


def build_chunks(source_path: str, source_type: str) -> list[dict]:
    path = Path(source_path)
    if not path.exists():
        print(f"  Skipping {source_path} (not found)")
        return []

    text = path.read_text(encoding="utf-8")
    sections = _split_into_sections(text)
    chunks = []
    for section in sections:
        chunks.extend(_chunk_section(section, source_type, path.stem))

    return chunks


# ---------------------------------------------------------------------------
# Embeddings
# ---------------------------------------------------------------------------

def embed_chunks(chunks: list[dict]) -> list[dict]:
    from sentence_transformers import SentenceTransformer

    print(f"  Cargando modelo {EMBED_MODEL}...")
    model = SentenceTransformer(EMBED_MODEL)

    texts = [c["content"] for c in chunks]
    print(f"  Generando {len(texts)} embeddings...")
    t0 = time.time()
    embeddings = model.encode(texts, batch_size=32, show_progress_bar=True, normalize_embeddings=True)
    print(f"  Embeddings generados en {time.time() - t0:.1f}s")

    for chunk, emb in zip(chunks, embeddings):
        chunk["embedding"] = emb.tolist()

    return chunks


# ---------------------------------------------------------------------------
# Base de datos
# ---------------------------------------------------------------------------

def get_connection():
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL no configurada en .env")
    conn = psycopg2.connect(DATABASE_URL)
    register_vector(conn)
    return conn


def delete_all_chunks(conn):
    with conn.cursor() as cur:
        cur.execute("DELETE FROM corpus_chunks WHERE corpus_version = %s", (CORPUS_VERSION,))
    conn.commit()
    print(f"  Chunks de {CORPUS_VERSION} eliminados.")


def get_existing_ids(conn) -> set[str]:
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM corpus_chunks")
        return {row[0] for row in cur.fetchall()}


def upsert_chunks(conn, chunks: list[dict], dry_run: bool = False):
    if dry_run:
        print(f"  [dry-run] Se insertarían {len(chunks)} chunks")
        for c in chunks[:3]:
            print(f"    - {c['id']}: {c['content'][:60]}...")
        return

    sql = """
        INSERT INTO corpus_chunks
            (id, content, embedding, source_type, source_document, section, parent_section, corpus_version, ingested_at)
        VALUES
            (%s, %s, %s, %s, %s, %s, %s, %s, NOW())
        ON CONFLICT (id) DO UPDATE SET
            content = EXCLUDED.content,
            embedding = EXCLUDED.embedding,
            corpus_version = EXCLUDED.corpus_version,
            ingested_at = NOW()
    """
    with conn.cursor() as cur:
        for chunk in chunks:
            cur.execute(sql, (
                chunk["id"],
                chunk["content"],
                chunk["embedding"],
                chunk["source_type"],
                chunk["source_document"],
                chunk["section"],
                chunk["parent_section"],
                chunk["corpus_version"],
            ))
    conn.commit()
    print(f"  {len(chunks)} chunks insertados/actualizados.")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Ingest corpus a pgvector")
    parser.add_argument("--dry-run", action="store_true", help="Muestra qué haría sin escribir")
    parser.add_argument("--fresh", action="store_true", help="Borra chunks existentes y re-inserta todo")
    parser.add_argument("--update", action="store_true", help="Solo inserta chunks nuevos")
    args = parser.parse_args()

    if not args.dry_run and not DATABASE_URL:
        print("ERROR: DATABASE_URL no configurada en .env")
        sys.exit(1)

    print(f"\nCorpus version: {CORPUS_VERSION}")
    print(f"Modo: {'dry-run' if args.dry_run else 'fresh' if args.fresh else 'update'}\n")

    # 1. Construir chunks
    all_chunks: list[dict] = []
    for source_path, source_type in SOURCES:
        print(f"Procesando {source_path}...")
        chunks = build_chunks(source_path, source_type)
        print(f"  -> {len(chunks)} chunks")
        all_chunks.extend(chunks)

    print(f"\nTotal chunks: {len(all_chunks)}")

    if not all_chunks:
        print("No hay chunks para ingestar.")
        return

    # 2. Embeddings
    print("\nGenerando embeddings...")
    all_chunks = embed_chunks(all_chunks)

    if args.dry_run:
        print("\n[dry-run] Resultado:")
        upsert_chunks(None, all_chunks, dry_run=True)
        return

    # 3. Conectar a BD
    print("\nConectando a Supabase...")
    conn = get_connection()

    if args.fresh:
        print("Modo --fresh: eliminando chunks previos...")
        delete_all_chunks(conn)

    if args.update:
        existing = get_existing_ids(conn)
        all_chunks = [c for c in all_chunks if c["id"] not in existing]
        print(f"Modo --update: {len(all_chunks)} chunks nuevos a insertar")

    # 4. Upsert
    print("\nInsertando en pgvector...")
    upsert_chunks(conn, all_chunks)

    conn.close()
    print(f"\nIngest completo. Corpus version {CORPUS_VERSION} activa.")


if __name__ == "__main__":
    main()
