-- Migración 007: cache semántico de respuestas (plan de mejoras 2.3).
--
-- Motivo: el cache exacto (app/cache.py) es SHA-256 de la pregunta normalizada,
-- así que CADA paráfrasis de la misma pregunta es un miss y paga una llamada
-- completa al LLM. En free tier eso es lo que agota la cuota (2026-07-14: dos
-- corridas de eval bastaron para quedarnos sin ella).
--
-- Reparto de responsabilidades: esta tabla guarda embedding -> cache_key; la
-- RESPUESTA sigue viviendo en Redis bajo esa clave. Un hit semántico es un
-- lookup de puntero seguido del GET normal de Redis.
--
-- Se guarda también el texto de la pregunta: el gate de esta feature es "cero
-- falsos positivos leídos a mano", y sin la pregunta que matcheó no hay forma
-- de auditar un match.
CREATE TABLE IF NOT EXISTS cached_questions (
  id BIGSERIAL PRIMARY KEY,
  question TEXT NOT NULL,
  embedding VECTOR(1024) NOT NULL,
  -- Apunta a la entrada de Redis (misma clave que make_cache_key).
  cache_key TEXT NOT NULL UNIQUE,
  -- Dimensiones de namespace: un vecino sólo es candidato si coincide en las
  -- TRES. Son las mismas que make_cache_key ya hashea, replicadas como columnas
  -- para poder filtrarlas en el WHERE del ANN. Sin esto, un hit semántico
  -- podría cruzar un borde de corpus/prompt/cartas y servir una respuesta
  -- generada bajo otras condiciones.
  corpus_version TEXT NOT NULL,
  prompt_version TEXT NOT NULL,
  directive_key TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- HNSW, no ivfflat: misma lección que la migración 003 — ivfflat sub-recuperaba
-- gravemente al filtrar por una columna (lists mal dimensionado a esta escala).
-- HNSW da recall ~100% sin tuning y es robusto a inserts, que acá son continuos.
CREATE INDEX IF NOT EXISTS cached_questions_embedding_hnsw_idx
  ON cached_questions USING hnsw (embedding vector_cosine_ops)
  WITH (m = 16, ef_construction = 64);

-- El ANN filtra siempre por las tres columnas de namespace + created_at.
CREATE INDEX IF NOT EXISTS cached_questions_namespace_idx
  ON cached_questions (corpus_version, prompt_version, directive_key, created_at);
