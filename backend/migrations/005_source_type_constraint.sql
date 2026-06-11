-- Migración 005: alinea el CHECK de source_type con lo que el código produce,
-- y elimina la tabla `cards` que 001 creó pero nunca se usó.
--
-- 001 definía CHECK (source_type IN ('rulebook', 'faq', 'errata', 'card_text')),
-- valores que el pipeline de ingest (scripts/ingest.py SOURCES) ya no escribe:
-- usa 'rulebook', 'tournament_rules', 'patch_notes', 'rules_faq', 'errata', 'card'.
-- El parche vivía en scripts/fix_constraint.py y fix_constraint_v2.py, fuera de la
-- cadena de migraciones — una base fresca reconstruida desde migrations/ rechazaba
-- el corpus. Esta migración consolida esos scripts y los reemplaza.
--
-- Idempotente: DROP ... IF EXISTS + nombre de constraint estable.
ALTER TABLE corpus_chunks DROP CONSTRAINT IF EXISTS corpus_chunks_source_type_check;

ALTER TABLE corpus_chunks
  ADD CONSTRAINT corpus_chunks_source_type_check
  CHECK (source_type IN (
    'rulebook',
    'tournament_rules',
    'patch_notes',
    'rules_faq',
    'errata',
    'card'
  ));

-- La tabla `cards` se creó en 001 para "entity resolution" pero nunca se cableó;
-- los datos de cartas viven como chunks con source_type='card'.
DROP TABLE IF EXISTS cards;
