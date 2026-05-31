-- Migración 003: reemplaza el índice ivfflat por HNSW.
--
-- Motivo: el índice ivfflat (lists=100) sub-recuperaba gravemente al filtrar por
-- corpus_version. Medición de recall@5 (probes=1, default prod):
--   v1.3.0 -> 14%   v2.0.0 -> 0%
-- v2.0.0 necesitaba probes=50 (escanear media tabla) para recall full, anulando
-- el beneficio del índice. lists=100 estaba mal dimensionado para ~2000 vectores.
--
-- HNSW da recall ~100% sin tuning de probes/lists, escala y es robusto a inserts.
-- A esta escala el build es instantáneo.
DROP INDEX IF EXISTS corpus_chunks_embedding_idx;

CREATE INDEX IF NOT EXISTS corpus_chunks_embedding_hnsw_idx
  ON corpus_chunks USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);
