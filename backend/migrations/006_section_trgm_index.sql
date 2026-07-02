-- Migración 006: índice trigram sobre LOWER(section) para tagged_lookup.
--
-- tagged_lookup (app/rag/retrieval.py) hace, una vez por tag:
--   WHERE LOWER(section) ILIKE LOWER('%tag%')
-- El comodín inicial '%' impide que un btree sirva, así que cada tag disparaba
-- un seq scan de corpus_chunks. Con corpus chico no se nota; a escala son K
-- full-scans por request.
--
-- Un índice GIN trigram sobre la EXPRESIÓN lower(section) vuelve indexable el
-- ILIKE con comodín en ambos lados SIN cambiar la semántica de match (substring,
-- case-insensitive). pg_trgm ya está habilitada (migración 001) y ya existe un
-- índice equivalente sobre cards.name.
CREATE INDEX IF NOT EXISTS corpus_chunks_section_trgm_idx
  ON corpus_chunks USING gin (LOWER(section) gin_trgm_ops);
