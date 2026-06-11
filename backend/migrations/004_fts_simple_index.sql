-- Migración 004: corrige la configuración del índice FTS.
--
-- El índice de 001 se creó con to_tsvector('english', content), pero la query
-- de retrieval (app/rag/retrieval.py, _FTS_SQL) usa to_tsvector('simple', ...).
-- Postgres solo usa un índice GIN de FTS si la regconfig coincide EXACTAMENTE,
-- así que el índice 'english' nunca se usaba: cada FTS hacía un seq scan +
-- to_tsvector en runtime sobre toda la tabla. Con corpus chico no se nota en
-- latencia, pero es un índice muerto.
--
-- Elegimos 'simple' (no 'english') a propósito: el corpus mezcla términos de
-- juego en inglés y texto en español, y 'simple' no aplica stemming ni stopwords
-- de un idioma, evitando que "showdown"/"combat" se recorten o se descarten.
DROP INDEX IF EXISTS corpus_chunks_content_fts_idx;

CREATE INDEX IF NOT EXISTS corpus_chunks_content_fts_idx
  ON corpus_chunks USING gin(to_tsvector('simple', content));
