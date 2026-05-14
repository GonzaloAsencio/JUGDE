-- Enable extensions
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pg_trgm;

-- Corpus chunks: stores all text chunks with embeddings
CREATE TABLE IF NOT EXISTS corpus_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content TEXT NOT NULL,
  embedding VECTOR(1024),
  source_type TEXT NOT NULL CHECK (source_type IN ('rulebook', 'faq', 'errata', 'card_text')),
  source_document TEXT NOT NULL,
  section TEXT,
  parent_section TEXT,
  metadata JSONB,
  corpus_version TEXT NOT NULL,
  ingested_at TIMESTAMP,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS corpus_chunks_embedding_idx
  ON corpus_chunks USING ivfflat (embedding vector_cosine_ops)
  WITH (lists = 100);

CREATE INDEX IF NOT EXISTS corpus_chunks_content_fts_idx
  ON corpus_chunks USING gin(to_tsvector('english', content));

CREATE INDEX IF NOT EXISTS corpus_chunks_version_idx
  ON corpus_chunks (corpus_version);

-- Cards: individual card data (used for entity resolution if enabled)
CREATE TABLE IF NOT EXISTS cards (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  alternate_names TEXT[],
  set_code TEXT,
  type TEXT,
  faction TEXT,
  cost INTEGER,
  text TEXT,
  keywords TEXT[],
  metadata JSONB,
  embedding VECTOR(1024),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS cards_name_trgm_idx
  ON cards USING gin(name gin_trgm_ops);
