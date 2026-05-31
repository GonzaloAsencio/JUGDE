-- Migración 002: índice para filtrar chunks por expansión (set_filter).
--
-- La query de retrieval filtra con:
--   WHERE corpus_version = %s
--     AND (metadata->>'set' = %s OR metadata->>'set' = 'core')
--
-- Un índice GIN sobre la columna JSONB acelera operadores de contención
-- (@>, ?, ?|), NO el operador `->>'set' =` (igualdad sobre texto extraído).
-- Para esa igualdad el índice correcto es un btree sobre la EXPRESIÓN, y como
-- la query siempre antepone corpus_version, lo óptimo es un compuesto.
CREATE INDEX IF NOT EXISTS corpus_chunks_version_set_idx
  ON corpus_chunks (corpus_version, (metadata->>'set'));
