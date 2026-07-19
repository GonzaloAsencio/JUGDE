-- Migración 009: ledger auditable de consumo de tokens (Fase 5, plan §5.1).
--
-- Una fila por respuesta servida (generación fresca O cache hit), SIN texto de
-- la pregunta — cero PII: user_id es un identificador opaco (anon:{uuid} |
-- auth:{sub} | ip:{addr}) que acuña el proxy detrás del secret compartido,
-- nunca el cliente. estimated distingue conteos reales de la API de la
-- heurística chars/4 (HyDE y streams sin usage). cached=true registra el hit
-- con 0 tokens gastados: la métrica "cuánto ahorró el cache" sale de acá.
--
-- model deja la puerta abierta a BYOK (plan 5.5, fuera de esta iteración).
-- Crecimiento sin prune: aceptado para la demo (anotado en el plan).
CREATE TABLE IF NOT EXISTS usage_ledger (
    id BIGSERIAL PRIMARY KEY,
    user_id TEXT NOT NULL,
    ts TIMESTAMPTZ NOT NULL DEFAULT now(),
    model TEXT,
    prompt_tokens INTEGER NOT NULL DEFAULT 0,
    output_tokens INTEGER NOT NULL DEFAULT 0,
    total_tokens INTEGER NOT NULL DEFAULT 0,
    estimated BOOLEAN NOT NULL DEFAULT FALSE,
    cached BOOLEAN NOT NULL DEFAULT FALSE
);

-- Lecturas dominantes: "cuánto gastó este usuario hoy" (verificación del
-- contador Redis) y ventanas recientes por usuario.
CREATE INDEX IF NOT EXISTS idx_usage_ledger_user_ts ON usage_ledger (user_id, ts DESC);
