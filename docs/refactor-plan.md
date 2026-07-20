# Refactor Plan — Judge (spec-driven)

> Fuente de verdad del refactor. Se ejecuta **paso a paso**, tachando tareas.
> Regla de oro: **cada fase corre su suite verde ANTES y DESPUÉS**. Sin suite verde,
> "no rompí nada" es fe, no ingeniería.

## Intent

El repo Judge (~25K LOC, backend FastAPI + frontend Next.js 16) está **sano** pero
tiene deuda estructural localizada. Objetivo: pagar esa deuda sin cambiar comportamiento
observable, apoyándose en la red de tests existente (pytest 53 archivos + Jest 32).

## Scope

- **In:** backend `app/` + `app/rag/` + `scripts/`, frontend `app/`/`components/`/`lib/`/`store/`.
- **Out:** `frontend/lib/cardIndex.ts` (generado — se regenera con `scripts/parse_cards.py`),
  cambios de comportamiento/feature, cambios de infra o deploy.

## Contrato de verificación (todas las fases)

```
Backend:  cd backend  && pytest         # 53 archivos, corre en CI en cada PR
Frontend: cd frontend && npm test       # Jest 32 archivos + jest-axe (a11y)
Lint:     cd frontend && npm run lint
```

Una tarea NO se marca `[x]` hasta que su suite quede verde. Cada fase = una rama + un PR.

---

## Fase 0 — Fundacional: enforcement backend  `[x]`

Habilita todo lo demás. Cero cambios de lógica.

- [x] Agregar `backend/pyproject.toml` con `ruff` (F/I imports, BLE001 broad-except, C901 complejidad, ASYNC, UP, SIM).
- [x] Agregar `mypy` en modo gradual (laxo, no bloqueante).
- [x] Agregar `.pre-commit-config.yaml` (ruff + ruff-format).
- [x] Correr `ruff check` y anotar el inventario (diagnóstico, sin arreglar).

**Config afinada** para no meter ruido falso: `E402` ignorado en `scripts/` (patrón `load_dotenv()` legítimo);
`B008` desactivado para FastAPI `Depends/Query/…` (idiom, no el footgun de default mutable).

**Inventario baseline (248 hallazgos reales, 132 auto-fixeables):**

| Regla | # | Alimenta fase |
|-------|---|---------------|
| SIM117 multiple-with | 89 | 6 (higiene) |
| I001 unsorted-imports | 55 | auto-fix |
| BLE001 blind-except | 28 | 3 / 6 |
| UP045 Optional→`\| None` | 14 | auto-fix |
| F401 unused-import | 13 | 1 / 3 (main.py `google.genai`) |
| C901 complex-structure | 5 | 3 (lifespan) |
| F841 unused-var, F811 redefinido | 3 | 1 |
| resto (E401/E741/UP035/…) | 41 | 6 |

**Gate:** ✅ 799 tests colectan sin error; subset de validación 13/13 verde; suite completo lo corre CI en el PR.
Fase 0 no tocó runtime → resultado de pytest idéntico al baseline.

---

## Fase 1 — Código muerto: borrados seguros  `[x]`

Los tests confirman que nada de esto se usa. Máximo valor, mínimo riesgo.

- [x] Frontend: borrar `components/ExampleQueries.tsx`, `components/CitationsList.tsx`, `components/JudgeIntroAnimation.tsx` (+ su test huérfano).
- [x] Frontend: borrar `postQuery` + `CLIENT_TIMEOUT_MS` de `lib/api.ts` (+ el import `QueryResponse` que quedó huérfano).
- [x] Frontend: quitar prop muerta `leaving` de `LandingHero.tsx` (verificado: `page.tsx:39` no la pasa).
- [x] Backend: borrar la cadena `rewrite_query` muerta — base ABC `LLMProvider.rewrite_query`, override `OpenAICompatProvider.rewrite_query`, `_rewrite_openai_compat`, `_REWRITE_PROMPT`.

**Verificación previa:** grep confirmó cero callers en producción; `rewrite_experiment.py` menciona `_REWRITE_PROMPT` solo en el docstring (no lo importa).

**Gate:** ✅ backend 200 tests (provider/generation/pipeline) verdes + imports OK; frontend 31 suites / 230 tests verdes.
Nota: `npm run lint` tiene 1 error preexistente en `SystemNotice.tsx:76` (`Date.now` en render) — NO introducido acá, ya es target de Fase 6.

---

## Fase 2 — HIGH #1: consolidar `generation.py`  `[x]`

El de mayor impacto. Boilerplate LLM duplicado 4×.

- [x] Helper único `_raise_provider_error(e, provider=...)` para el mapeo `timeout/deadline → GenerationTimeout else GenerationError` (era 4×). Unifica las 2 variantes; `deadline` queda como superset inofensivo para OpenAI-compat.
- [x] `_gemini_config(...)` unifica el `GenerateContentConfig` (era Gemini ×3) — bonus: elimina el `import types` local de las 3.
- [x] `_openai_messages(...)` unifica el bloque `messages=[system,user]` (era OpenAI ×2).

**Resultado:** `GenerateContentConfig` 3→1, `error_str` 4→1, `messages=[system,user]` 2→1. Un cambio de clasificación ahora se hace en UN lugar.

**Gate:** ✅ 200 tests (generation/provider/pipeline) verdes; F-clean (sin imports huérfanos); import smoke OK. Los 11 BLE001 restantes son preexistentes (Fase 6).

---

## Fase 3 — HIGH #2: descomponer `lifespan`  `[x]`

`app/main.py`, ~100 líneas, 10 responsabilidades.

- [x] Cortar en helpers nombrados: `_init_llm_client` (Gemini client + ping), `_init_cache` (Redis), `_wire_app_state` (providers + app.state). `lifespan` queda como orquestador legible top-to-bottom. C901 ya no lo marca.
- [x] Matar el `__import__(...)` hackeado (`:32-34`) → import normal `from app.observability import _before_send_filter`. Ordenado el import de `google` (arregla un I001).
- [x] ⚠️ **NO** se removió el import top-level de `google.genai`: los tests hacen `patch("app.main.genai.Client")` — es un seam de testing deliberado. Removerlo rompía 14 tests por ningún beneficio real (genai ya es dependencia dura). Decisión: mantenerlo.

**Gate:** ✅ 68 tests (health/query/usage/main/startup) verdes; ruff F/I/C901 limpio; import smoke OK. Baseline restaurado tras detectar y corregir la ruptura del seam.

---

## Fase 4a — Red de integración BD (prerequisito)  `[x]`

**Hallazgo que forzó esto:** toda la Fase 4 cambia SQL, pero TODOS los tests mockean el cursor → cero verificación de correctitud del SQL. Cambiar SQL de retrieval sin red viola la disciplina de medición del proyecto. Decisión del usuario: **red de integración primero.**

- [x] Harness `tests/integration/` con `testcontainers` + imagen `pgvector/pgvector:pg16`, migraciones en orden, pool real vía `app.db.init_pool`. Marker `integration` + skip si no hay Docker.
- [x] Caracterización de `tagged_lookup` (LIMIT-2-por-tag, dedup, orden card>rulebook, scope de version, similarity 0.0) contra Postgres real.
- [x] Caracterización de `family_lookup` (match exacto, sin límite, scope de version).
- [x] Caracterización de `upsert_chunks` (ON CONFLICT DO UPDATE, metadata) y `get_existing_ids` — incluyendo el comportamiento cross-version ACTUAL, para que la 4b lo cambie visiblemente.

**Gate:** ✅ 14 tests de integración verdes contra Postgres real; 813 colectan sin error; ruff limpio. CI (ubuntu tiene Docker) los corre solo con la dep agregada.

## Fase 4b — Ineficiencias de BD (con la red puesta)  `[x]`

- [x] `retrieval.tagged_lookup`: N+1 colapsado a UN round-trip con `unnest(...) WITH ORDINALITY` + `LATERAL`, preservando LIMIT-2-por-tag y orden por tag. La caracterización 4a fue el árbitro (9/9 verdes tras el cambio).
- [x] `scripts/ingest.py`: `get_existing_ids` con `WHERE corpus_version` (test de caracterización actualizado deliberadamente a scoped); `--update` filtra ANTES de embeder (dry-run ya no embebe tampoco); `upsert_chunks` con `execute_values` (batch en un round-trip). Drive-by: quitado import muerto `hashlib`.
- [x] Tests mockeados acoplados a la estructura vieja: actualizado el de merge de tags (1 execute ahora); removidos los 2 de upsert mockeado (incompatibles con `execute_values` + ya cubiertos por integración).

**Gate:** ✅ integración 14/14 verdes ANTES y DESPUÉS; barrido amplio 304 tests (retrieval/pipeline/routing/ingest) verde. Nota: `main()` de ingest no tiene test (orquestación CLI) — el reorden es verificable a ojo y dry-run/output quedan idénticos.

---

## Fase 5 — Config + scripts (más invasivo, al final)  `[ ]`

- [ ] Unificar config en `Settings`: `rate_limit.py:53` y `scripts/ingest.py:25-26` que hoy leen `os.getenv` directo (o documentar explícitamente la excepción del limiter en import-time).
- [ ] Extraer `scripts/_common.py` (conexión DB + carga de embedder) y migrar los 26/43 scripts que reimplementan la infra.

**Gate:** `pytest` verde + humo de los scripts migrados más usados (`build_corpus`, `ingest`, `parse_cards`).

---

## Fase 6 — Frontend perf/correctness + higiene  `[ ]`

- [ ] `ChatView.tsx:21-23`: throttle/keyear el `scrollIntoView` para no re-disparar por token.
- [ ] `AnswerDisplay.tsx:195`: hoist `makeComponents()` a constante de módulo / `useMemo`.
- [ ] `SystemNotice.tsx:84-86`: reinicializar `remaining` cuando llega un 429 nuevo con `retryAfter` distinto.
- [ ] Higiene (barrido único): determinismo de `frozenset` (`_detect_keywords:97`), bare-excepts sin log, comentarios que restan valor, timers sin cleanup, `img` sin `eslint-disable` consistente.

**Gate:** `npm test` (incl. jest-axe) + `npm run lint` verdes.

---

## Progreso

| Fase | Estado | Rama / PR |
|------|--------|-----------|
| 0 — Enforcement backend | ✅ hecho | refactor/phase-0-backend-linting |
| 1 — Código muerto | ✅ hecho | refactor/phase-1-dead-code |
| 2 — generation.py | ✅ hecho | refactor/phase-2-generation-dedup |
| 3 — lifespan | ✅ hecho | refactor/phase-3-lifespan |
| 4a — Red integración BD | ✅ hecho | refactor/phase-4a-db-integration-harness |
| 4b — Ineficiencias BD | ✅ hecho | refactor/phase-4b-db-efficiency |
| 5 — Config + scripts | ⬜ pendiente | — |
| 6 — Frontend + higiene | ⬜ pendiente | — |

> Detalle completo de cada hallazgo con `archivo:línea`:
> `C:\Users\gonch\.claude\plans\act-a-como-un-ingeniero-federated-popcorn.md`
