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

## Fase 1 — Código muerto: borrados seguros  `[ ]`

Los tests confirman que nada de esto se usa. Máximo valor, mínimo riesgo.

- [ ] Frontend: borrar `components/ExampleQueries.tsx`, `components/CitationsList.tsx`, `components/JudgeIntroAnimation.tsx` (+ sus tests huérfanos).
- [ ] Frontend: borrar `postQuery` + `CLIENT_TIMEOUT_MS` (`lib/api.ts:60-94, :3`).
- [ ] Frontend: quitar prop muerta `leaving` de `LandingHero.tsx:9,57,70`.
- [ ] Backend: borrar la cadena `rewrite_query` muerta (`provider.py:255-262`, `generation._rewrite_openai_compat:434-451`, `_REWRITE_PROMPT:423-431`) + sus tests.

**Gate:** ambas suites verdes. Si un borrado rompe un test que NO sea el del propio huérfano → ese código no estaba muerto, revertir y re-evaluar.

---

## Fase 2 — HIGH #1: consolidar `generation.py`  `[ ]`

El de mayor impacto. Boilerplate LLM duplicado 4×.

- [ ] Extraer helper único para el mapeo `timeout/deadline → GenerationTimeout else GenerationError` (hoy en `:416-420, :582-586, :642-646, :693-697`).
- [ ] Unificar construcción de `GenerateContentConfig` (Gemini ×3) y del bloque `messages=[system,user]` (OpenAI ×2).

**Gate:** `pytest` verde, especialmente los tests de clasificación de error/timeout.

---

## Fase 3 — HIGH #2: descomponer `lifespan`  `[ ]`

`app/main.py:40-146`, ~100 líneas, 10 responsabilidades.

- [ ] Cortar en helpers nombrados (`_init_observability`, `_init_db`, `_init_embedder`, `_init_llm`, `_init_cache`, …) siguiendo los propios comentarios `# 1.`…`# 10.`.
- [ ] De paso: matar el `__import__(...)` hackeado (`:32-34`, ya importado en `:15`) y el import incondicional de `google.genai` (`:16`).

**Gate:** `pytest` verde + arranque local del backend sin error.

---

## Fase 4 — Ineficiencias de BD  `[ ]`

- [ ] `retrieval.tagged_lookup:301-318`: colapsar el N+1 (un round-trip por tag) en una query, espejando `family_lookup:346-358` (`= ANY(%s)`).
- [ ] `scripts/ingest.py`: filtrar `get_existing_ids` por `corpus_version` (`:352-355`); filtrar ANTES de embeder en `--update` (`:315-330,439,456`); upsert con `execute_values` en vez de row-by-row (`:377-390`).

**Gate:** `pytest` verde + un `ingest --update` de humo local sin regresión de conteos.

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
| 1 — Código muerto | ⬜ pendiente | — |
| 2 — generation.py | ⬜ pendiente | — |
| 3 — lifespan | ⬜ pendiente | — |
| 4 — Ineficiencias BD | ⬜ pendiente | — |
| 5 — Config + scripts | ⬜ pendiente | — |
| 6 — Frontend + higiene | ⬜ pendiente | — |

> Detalle completo de cada hallazgo con `archivo:línea`:
> `C:\Users\gonch\.claude\plans\act-a-como-un-ingeniero-federated-popcorn.md`
