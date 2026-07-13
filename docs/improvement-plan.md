# Plan de Mejoras — Judge (Riftbound RAG Assistant)

> Resultado de la revisión de arquitectura de julio 2026 (rama `feat/gemini-hyde`).
> Restricción global: **todo debe funcionar en free tier ($0)**. Cada fase se mide
> con el harness LLM-as-judge existente antes de pasar a la siguiente.
> Regla de método: **una variable por vez, eval después de cada cambio.**

---

## Estado actual (actualizado 2026-07-12 — post gate 3.8)

| Métrica | Valor |
|---|---|
| Recall determinístico (eval anotado, 17/20 evaluables) | **12/17 estricto** (matcher honesto post-#55); 14/17 con el matcher viejo que contaba hits de familia |
| Correct rate (judge) | ⚠️ NO usable como métrica de PR: varianza ±10pp medida (runs idénticos dieron 25–45%) |
| Modelo | `gemini-flash-lite-latest` (Google retiró el free tier de 2.0-flash: limit 0) |
| Corpus | **v2.2.1** activo en prod (secciones finas + fix de títulos familia-oración, #54) |
| Reranker | **ON por default** (+3 hits de recall, 0 pérdidas, cero tokens LLM) |
| Costo | $0 (sin cambios) |

Misses de retrieval restantes (3/17, re-verificados 2026-07-11 con A/B pareado):
eval-014 y eval-015 (ambos 383.3.d.1, regla-cuerpo sin título propio) y
eval-019 (429.2 — "Add" no es taggeable sin ruido). eval-036 (143.2) YA ES HIT
en el baseline actual — la lista anterior estaba desactualizada. Necesitan un
enfoque distinto al de #48.

> ⚠️ Hallazgo 2026-07-11: el "recall determinístico" NO es 100% determinístico.
> `provider.hyde()` falla intermitente y devuelve `''` silencioso (contrato
> never-raise), y hay preguntas borderline (eval-036: gold en rank 10) cuyo hit
> depende de si HyDE respondió en ese run. Higiene pendiente del eval: loggear
> hyde-vacío por pregunta para poder descartar runs contaminados. Relacionado:
> el bug de logging `query.complete model=llm_model` sigue vivo — muestra el
> LLM_MODEL del .env aunque el provider real sea gemini.

> ⚠️ Los números del baseline original (45% correct / hard 27% / recall 59%)
> eran de gemini-2.0-flash + eval set sin anotar + chunks gordos — NO comparables
> con nada posterior al 2026-07-10. Además el recall viejo contaba **hits de
> papel**: códigos gold incidentales dentro de blobs de 500 tokens que el LLM no
> aprovechaba (eval-028/037 eran "hit" y siempre contestaban mal).

---

## Fase 0 — Diagnóstico ✅ COMPLETA (2026-07-10)

**Objetivo:** separar los fallos del bucket hard en *retrieval* vs *razonamiento*.

- [x] Script que cruce los veredictos del judge con el recall determinístico →
      `scripts/diagnose_hard.py` (mergeado en #44).
- [x] Breakdown de fallos por `tags` → `specific-card` domina (9 fallos).
- [x] Anotar gold refs en las preguntas sin ellas → 7 anotadas (#44) + eval-019/030
      reemplazadas por QOTDs de la comunidad ya anotadas (#47). **0 unknowns.**

**Salida: 6 retrieval / 4 reasoning sobre 10 fallos hard clasificables (60/40).**
Advertencia metodológica descubierta después: parte de los "reasoning failures"
eran hits de papel (ver Estado actual) — el split real inclina AÚN más a retrieval,
que era exactamente lo que #48 atacó.

---

## Fase 1 — Fixes de la revisión (rápidos, independientes del diagnóstico)

### 1.1 ✅ No cachear respuestas degradadas (bug real) — HECHO (rama `fix/skip-caching-degraded-responses`)
`pipeline.py::answer_question` cacheaba 24h incondicionalmente. Un fallo transitorio
(`_SAFE_FALLBACK`, `_INCONCLUSIVE_ANSWER`, no-info-despite-context) quedaba congelado
para todos los usuarios.
- [x] Saltear `set_cached` cuando `confidence == 0.0` o el answer es una constante
      de fallback (`_DEGRADED_ANSWERS`). Se eligió saltear (no TTL corto): el rate
      limit ya acota el costo de regenerar.
- [x] Tests: inconclusive y safe-fallback no se cachean; respuesta buena sí
      (guarda de regresión).

### 1.2 ✅ Acotar tokens de salida de la generación — HECHO (PR #51)
`_call_gemini` no seteaba `max_output_tokens` — el costo de output (el lado caro)
no tenía techo. HyDE sí lo acota (160); la llamada principal no.
- [x] `Settings.max_output_tokens = 1024`, pasado por ambos providers (Gemini y
      openai-compat). El warning `gemini.max_tokens` ahora es alcanzable: si
      aparece en logs de queries reales, subir el budget por env.

### 1.3 ✅ Documentar drift de contrato: `confidence` — HECHO (PR #52)
Spec 05 dice `Literal["high","medium","low"]`; el código expone float 0–1.
- [x] Nota en Spec 05 (bloque del schema) + README; fuente de verdad
      `schemas.py::QueryResponse`.

### 1.4 ✅ Anotar supuesto de infraestructura del rate limiting — HECHO (PR #52)
`X-Real-IP` toma el primer hop de `x-forwarded-for`. Hoy es seguro porque Vercel
sobreescribe XFF; si el proxy se muda de host, pasa a ser spoofeable (buckets
infinitos → quota de Gemini quemada).
- [x] Comentario en `frontend/app/api/query/route.ts` + nota en el README.

---

## Fase 2 — Costo y latencia (proteger el free tier)

### 2.1 HyDE adaptativo
HyDE duplica las llamadas LLM en cada query no cacheada. Las preguntas fáciles ya
recuperan bien con el brazo crudo.
- [ ] Correr el brazo crudo primero; si el mejor coseno ≥ umbral (~0.75, calibrar
      con eval set), saltear HyDE.
- [ ] Medir: recall@5 no debe caer; llamadas LLM/query deben bajar.

### 2.2 Modelo liviano para HyDE
`GeminiProvider.hyde()` usa el MISMO modelo que la generación para escribir 2-3
oraciones descartables.
- [ ] Nuevo setting `hyde_model` (p. ej. flash-lite); default al modelo actual para
      no romper nada.

### 2.3 Cache semántico (la mayor palanca de costo)
El embedder es local (costo cero) y pgvector ya está. El cache exacto SHA-256
pierde todas las paráfrasis.
- [ ] Tabla `cached_questions(embedding vector, cache_key text, corpus_version,
      prompt_version, ts)`.
- [ ] En cache-miss exacto: ANN sobre preguntas cacheadas, umbral ≥0.95 → devolver
      la respuesta cacheada.
- [ ] Métrica: hit rate combinado (exacto + semántico).

### 2.4 Paralelizar los brazos de retrieval
Hoy: HyDE → embed → search → search → generate, todo secuencial.
- [ ] `ThreadPoolExecutor(2)`: brazo crudo (embed+search) en paralelo con la
      llamada HyDE. Ahorra ~1s de p50 sin tocar el modelo de concurrencia.

### 2.5 Streaming SSE (latencia percibida)
Ya identificado en FUTURE_WORK como short-term. Con respuestas que llevan un
Reasoning largo, el time-to-first-token importa más que el p50 total — es la
mejora de UX más rentable pendiente.
- [ ] Stream de la respuesta del LLM vía Server-Sent Events desde FastAPI,
      consumido en el frontend Next.
- [ ] Resolver la pieza bloqueante ya anotada: las respuestas cacheadas también
      deben "streamear" (no aparecer instantáneas) para no generar un salto de UX.

### 2.6 Acotar el Reasoning en preguntas simples
El "Reasoning:" obligatorio paga tokens de salida incluso en preguntas triviales.
- [ ] Probar "máximo 3 bullets de reasoning" en el prompt y correr el harness: si
      el bucket hard no cae, queda. (Alternativa: exigir reasoning largo solo en
      queries ruteadas como hard, ver 4.2.)

---

## Fase 3 — Retrieval para el bucket hard (EN CURSO — 2 golpes dados, quedan 3 misses)

Ordenadas por (impacto esperado ÷ esfuerzo). Todas gratis en plata.

### 3.0 ✅ HECHO (#48, no estaba en el plan original — salió del diagnóstico)
Secciones finas por título de regla interno + slot de contexto reservado para el
chunk de regla de una keyword detectada. **Recall 71% → 82%, cero pérdidas.**
Corpus v2.2.0 activo en prod. eval-026/028/030/037 resueltas.

### 3.1 ~~Expansión por códigos de regla (1-hop)~~ ❌ MUERTA POR EVIDENCIA
Diagnóstico 2026-07-10: en los 4 fallos vigentes, los chunks recuperados NO
citaban los códigos gold en su texto — la expansión 1-hop no arreglaba ninguno.
Re-evaluar solo si los misses futuros muestran códigos citados-pero-no-traídos.

### 3.2 ~~Descomposición de query multi-carta~~ ❌ MUERTA POR EVIDENCIA (2026-07-11, PR #53 cerrado)
Implementada completa detrás de flag (fusión N-aria + sub-queries determinísticas
por carta/keyword, trigger 2+ entidades) y medida con gate A/B pareado mismo día
(eval_results_20260711T041105Z ON vs 041628Z OFF): **0 wins, 1 pérdida real.**
- Los 3 targets (014/015/019) no se movieron: las sub-queries por carta traen
  CARTAS (que tagged_lookup ya garantiza en slots reservados), no las reglas gold.
- Mecanismo de la pérdida (eval-017, probe de retrieval): el gold "360. Abilities"
  colgaba en rank 8/10; el brazo `What does the card "Fiora Peerless" do?` inunda
  el pool fusionado con impresiones del campeón (Victorious/Grand Duelist/Metal)
  y lo evicta antes del reranker.
- La mitad keyword también es redundante: la regla propia del keyword ya la trae
  el slot reservado de #48.
- Re-evaluar solo con un diseño que recupere REGLAS relacionadas (no entidades),
  p.ej. sub-queries sobre la MECÁNICA de la pregunta — pero 3.5 ataca lo mismo
  más barato. El código quedó en la rama feat/query-decomposition (PR #53).

### 3.3 ✅ Cross-encoder reranker — HECHO Y EN PROD
`cross-encoder/ms-marco-MiniLM-L-6-v2` mergeado (#42), validado con eval gate
(+3 hits, 0 pérdidas) y **default ON** (#46). ~80MB RAM; opt-out por env.

### 3.4 Subir top_k
5 chunks es poco para hard (carta A + carta B + regla C + errata). Flash tiene
contexto de sobra.
- [ ] Probar top_k 8-10 (con reranker para sostener precisión). Cambio de Settings.

### 3.5 Expansión padre/vecinos (small-to-big) ✅ GANÓ EN VARIANTE FAMILIA (2026-07-12, flag off por default)
Probes primero (cero código): la variante del plan original — expandir a la
sección padre markdown vía `parent_section` — quedó **falsificada**: rescata
solo eval-030 a +7-25K tokens/query, y 014/015/017/019 no se rescatan con
NINGUNA expansión (su gold no está en nada adyacente a lo recuperado).
La variante que SÍ ganó: **completar la familia de regla del keyword detectado**
(mismo `section` label, p.ej. '809. Deflect' = 4 chunks ~344 tok). El slot
reservado de #48 metía solo el primer chunk de la familia (`_TAGGED_SQL LIMIT 2`
+ presupuesto de 1 slot); la regla que la pregunta necesitaba (809.1) vivía en
un hermano descartado.
- [x] `family_lookup` + `_complete_keyword_families`: los hermanos van DESPUÉS
      de top_k (nunca desalojan semánticos — el mecanismo que mató a 3.2),
      capeados por `keyword_family_extra` (familias de keyword: 2-9 chunks,
      ~200-950 tok; costo solo en queries con keyword).
- [x] Gate pareado flag 0 vs 8 (matcher estricto, HyDE memoizado): **WIN
      eval-030, cero pérdidas** → recall estricto 12/17 → 13/17.
- [ ] Flip en prod: `KEYWORD_FAMILY_EXTRA=8` por env (default 0 en código =
      byte-idéntico); flip del default en código después de validar en prod
      (mismo camino two-step que el reranker #42→#46).

### 3.6 FTS quirúrgico — ❌ MUERTO POR PROBE (2026-07-11, cero código)
El experimento se corrió contra sus dos preguntas objetivo (014/019, matcher
estricto post-#55). FTS clava el gold en #1 con las dos palabras JUSTAS
("triggered simultaneously", "priority resolving") — pero ninguna extracción
determinística las produce: keywords detectados ('stun'; 'priority'+'hunt') →
None; OR-de-palabras-de-contenido → None (chunks gold chicos pierden por
densidad); pregunta entera → None (AND). El mecanismo requiere términos que
NO están en la pregunta.

### 3.7 Cuarto brazo: rewrite — ❌ MUERTO POR PROBE para 014/019 (2026-07-11)
`rewrite_query` devuelve ambas preguntas VERBATIM (ya usan terminología
oficial) → ranks idénticos al original. Sin señal nueva para este perfil.
Nota adicional del mismo probe: gold de 014 está en vector rank 19 — entra a
un pool ensanchado, pero el reranker lo deja en 14/40 (misma brecha de
vocabulario que el bi-encoder). Ensanchar fetch/pool NO rescata. Gold de 019
ni aparece en vector top-60.

### 3.8 ~~Contextual retrieval en ingest~~ ❌ MUERTA POR GATE (2026-07-12, dos variantes)
Se construyó completa (scripts/contextualize.py con checkpoint/resume, 701 líneas
LLM generadas, ingest --context-file, ids version-scoped) y se gateó con
corpus_ab_probe pareado + matcher estricto contra v2.2.1. Dos variantes:
- **v2.3.0 (global, 701/701 líneas): PIERDE 1W/3L** (gana 030; pierde 026/027/036).
  Prepender contexto a TODOS los chunks mueve todos los embeddings — arregla uno,
  rompe tres que ya funcionaban.
- **v2.3.1 (selectiva, solo chunks < p25 = 331 chars, 173 líneas, criterio
  pre-registrado): EMPATA 1W/1L** (gana 030; pierde 026). Recuperó 027/036 —
  el mecanismo de dilución quedó confirmado — pero no gana neto.
- **eval-014, la motivación original, no flippeó en NINGUNA variante**: el cruce
  del piso de similitud medido aislado (0.5001 vs 0.4913) no sobrevive la
  competencia del pipeline real. Es puente de vocabulario y las context lines
  no lo tienden.
- Sin barrido de umbrales: con 17 preguntas, probar N thresholds hasta que uno
  "gane" es fitear ruido. Un criterio pre-registrado, una corrida, empate → muerta.
- Subproducto que SÍ queda: ids version-scoped (fix del chunk-theft entre
  versiones, verificado en la DB real: v2.2.1 intacta junto a v2.3.x) y las 701
  líneas en data/context_lines.json (cuota ya gastada, reutilizables).

### 3.9 Fine-tuning de bge-m3 (última bala)
- [ ] Pares sintéticos pregunta→chunk generados con el LLM, fine-tune local con
      sentence-transformers. Gratis en plata, caro en tiempo. Solo si 3.1–3.8 no
      alcanzan.

---

## Fase 4 — Razonamiento para el bucket hard (si Fase 0 dice "razonamiento")

### 4.1 Few-shot de encadenamiento en el prompt ⭐ — IMPLEMENTADO, falta medir (rama `feat/few-shot-chaining`)
El system prompt DESCRIBE cómo encadenar (regla 6) pero no lo MUESTRA.
- [x] 2 ejemplos trabajados Reasoning → Answer completos: "enters exhausted"
      (carta + regla) y Deflect-in-trash (809.1 → 365.1 → sin costo), marcados
      como forma-solamente (no citables). Instrucción explícita: cadena resuelta
      ⇒ concluir; ambigüedad solo si el contexto no resuelve.
- [x] Versionado: `prompt_version` v5 → v6 (invalida cache).
- [ ] MEDIR: la query Deflect-in-trash en prod + eval con majority voting del
      judge (ver criterio de Fase 4 — el correct% simple no sirve como gate).

### 4.2 + 4.3 Routing a thinking + full-rulebook stuffing — ✅ IMPLEMENTADO COMBINADO (2026-07-12, flag off, rama `feat/hard-query-routing`)
Los probes del 2026-07-12 (`scripts/rulebook_stuffing_probe.py`, 3 samples,
leídos a mano contra las canónicas) demostraron que las palancas SE COMBINAN:
- **Stuffing solo (flash-lite)**: rescata eval-019 (3/3 citando 429.2/429.2.a)
  y eval-015 en sustancia (3/3); eval-014 1/3 (cita 383.3.d pero nunca aplica
  383.3.d.1 — termina en "it depends"); eval-017 0/3 (concluye al revés).
  Controles 001/030 intactos. **Retrieval formalmente exculpado**: con los
  gold verificados presentes en el contexto, el fallo restante es razonamiento.
- **Stuffing + thinking (gemini-3.5-flash, max_out 8192)**: eval-014 3/3 con el
  mecanismo exacto de la canónica (turn player ordena primero → LIFO → Vex
  resuelve → can't-beats-can) y eval-017 3/3 ("el trigger ya está en el chain,
  no se rechequea"). **Los 4 misses residuales quedan cubiertos.**
- Factibilidad: ~79.5K tokens de prompt, 3-5s en flash-lite / 18-32s en
  3.5-flash, cero 429s con pace 25s. `gemini-2.5-flash` está CERRADO para la
  key (404 "no longer available to new users"); 3.5-flash disponible.

Implementación (una variable de prod: el flag):
- [x] Clasificador determinístico `is_hard_query` (cero LLM): **≥2 cartas O
      ≥2 keywords** — calibrado sobre el eval set anotado: rutea los 4 misses
      + 10 hard/medium más, cero easy. La señal de longitud se evaluó y
      descartó (no suma cobertura de targets).
- [x] `build_stuffed_chunks`: secciones de cartas detectadas (de `cards.md`,
      misma vocab que el probe) + rulebook entero como último chunk. Never-raise:
      sin archivos → camino RAG normal.
- [x] `HARD_QUERY_ROUTING` (default False), `hard_gemini_model=gemini-3.5-flash`,
      `hard_timeout_s=60` (probe pisó 32.3s; el timeout normal de 30s corta),
      `hard_max_output_tokens=8192` (el thinking gasta presupuesto de salida).
- [x] Citation del chunk rulebook con `rule_codes=[]` (si no, TODOS los códigos
      del juego entrarían en una citation: bloat + paper-hit del matcher).
- [x] Gate e2e local (pipeline real, DB + Gemini reales, flag forzado):
      **3 wins / 0 losses / 1 push**. eval-014/017/019 correctas con el
      mecanismo canónico (014 cita 383.3.d.1 textual); eval-001 (easy) NO
      rutea. El push: **eval-015 refusa 3/3 en 3.5-flash** — "flash the unit
      back" es slang sin anclaje en el reglamento y el thinking aplica la
      regla 1 del prompt (refusar lo no derivable) donde flash-lite
      improvisaba. Prod hoy la contesta MAL (miss de retrieval): incorrecto →
      refusal honesto es lateral, no regresión. Queda abierta como problema
      de VOCABULARIO de la pregunta, no de retrieval ni de razonamiento.
- [ ] Flip two-step: PR mergeada flag off → `HARD_QUERY_ROUTING=true` en Space
      env → validar en prod (eval-014 vía proxy Vercel) → flip default en código.
- ⚠️ Límites free-tier de gemini-3.5-flash (RPD/TPM) sin verificar bajo carga.
- ⚠️ Con el flag ON, el recall del eval pierde sentido en preguntas ruteadas
      (el contexto ya no viene del retrieval); gates de retrieval corren flag OFF.

### 4.4 Extracción de quotes antes de razonar
- [ ] Scaffold: paso 1 citar VERBATIM del contexto, paso 2 razonar solo sobre lo
      citado. Reduce puentes inventados entre reglas.

### 4.5 Self-refine (dos pasadas) — solo hard
- [ ] Draft → crítica ("¿cada paso cita contexto? ¿cadena de autoridad aplicada?")
      → revisión. Duplica costo: solo sobre queries ruteadas.

### 4.6 Self-consistency — último recurso
- [ ] 3 muestras a temperatura >0, el judge elige. Triplica costo; solo si
      4.1–4.5 no alcanzan.

---

## Fase 5 — Metering de tokens por usuario (demo de capacidad, $0)

Contexto decidido: es una **demostración de portfolio**, free tier, sin auth hoy;
en un hipotético futuro pagarían los usuarios. Diseño acordado:

### 5.1 Identidad anónima sin auth
- [ ] El proxy Next emite cookie `judge_uid` (UUID + firma HMAC con secret propio),
      HttpOnly, y la reenvía al backend como `X-User-Id`.
- [ ] Si el proyecto alguna vez pivotea: se reemplaza el UUID anónimo por el user id
      de Supabase Auth (free tier) — mismo header, mismo ledger, cero rediseño.
- [ ] **Privacidad (solo si hay usuarios reales)**: hoy no se guarda PII (identidad
      = IP, sin cuentas). Con cuentas reales cambia el cuadro: política de retención
      de las preguntas logueadas, revisar qué llega a Langfuse/Sentry (ya hay
      sanitización de DSN — extenderla a datos de usuario), y términos de uso.

### 5.2 Captura de consumo real
- [ ] `_call_gemini` / `_call_openai_compat_raw` / HyDE devuelven también
      `usage_metadata` (prompt/output/total tokens) — p. ej. un
      `GenerationResult(text, usage)`.
- [ ] Sumar HyDE + generación (+ retry) por query.

### 5.3 Almacenamiento y enforcement
- [ ] **Enforcement**: contadores diarios en Upstash Redis
      (`INCRBY tokens:{user_id}:{YYYYMMDD}` + TTL) — atómico, rápido, free tier.
- [ ] **Auditoría/demo**: tabla Postgres `usage_ledger(user_id, query_id, ts,
      model, prompt_tokens, output_tokens, total_tokens, cached bool)`.
- [ ] Dependency de FastAPI (no middleware — solo aplica a `/query`): chequea cuota
      diaria antes de generar; 429 con detalle si se excedió. Race check-then-act
      aceptable para demo (cuota blanda, overshoot máximo = 1 request).
- [ ] Los rate limits actuales de slowapi se MANTIENEN: protegen RPM; la cuota de
      tokens protege el presupuesto diario. Ejes distintos, ambos necesarios.

### 5.4 Visibilidad (el artefacto de portfolio)
- [ ] `GET /api/v1/usage` → tokens consumidos / restantes del usuario.
- [ ] Mostrar en el frontend ("Te quedan N tokens hoy").
- [ ] Métrica de venta: "el cache ahorró X tokens" (filas con `cached=true`).

### 5.5 BYOK opcional (el camino "pagan los usuarios" sin Stripe)
- [ ] Header `X-User-Gemini-Key`: provider por-request con la clave del usuario;
      esas requests saltean tu cuota. NUNCA loguear ni persistir la clave —
      solo en memoria por request.
- [ ] Futuro pago real: Stripe metered billing SOBRE el mismo ledger de 5.3.
      El ledger es el punto en común de todos los caminos — por eso se
      construye primero.

---

## Orden de ejecución recomendado (actualizado 2026-07-12)

```
Fase 0 ✅ ── split: 6 retrieval / 4 reasoning (0 unknowns)
Fase 1 ✅ ── 1.1 (#49), 1.2 (#51), 1.3+1.4 (#52) mergeados y deployados
Fase 4.1 ✅ ── few-shot v6 (#50) mergeado; validado en prod: Deflect-in-trash
          contesta correcto (2026-07-11)
Fase 3 ── 3.0 ✅ (#48), 3.3 ✅ (#42/#46), 3.5 ✅ (variante familia, flag);
          3.1 ❌ 3.2 ❌ 3.6 ❌ 3.7 ❌ 3.8 ❌ muertas por evidencia
          (probes y gates pareados, matcher estricto)
Fase 4.2+4.3 ── IMPLEMENTADO COMBINADO (2026-07-12, rama feat/hard-query-routing,
          flag off): probes probaron que stuffing+thinking cubre los 4 misses
          residuales (014/015/017/019). 3.5 ya flippeado en prod vía env
          (KEYWORD_FAMILY_EXTRA=8, validado con eval-030).
SIGUIENTE RECOMENDADO:
PR de 4.2+4.3 → gate targeted por pregunta → flip HARD_QUERY_ROUTING en prod
          (two-step). Pendientes menores: flip default keyword_family_extra
          0→8 tras soak; 3.9 (fine-tune) queda como última bala si algo se cae.
Fase 2 / Fase 5 ── sin cambios, cuando toquen
```

## Criterio de "listo" por fase (revisado tras medir la varianza del judge)

- ~~Fase 0~~ ✅ split publicado.
- Fase 1: los 4 checks cerrados, tests verdes.
- Fase 2: llamadas LLM/query ↓ y hit rate ↑, sin caída de recall determinístico.
- Fase 3: recall determinístico ↑ por pregunta (wins/losses, no promedio) —
  el A/B por pregunta de #48 es el formato de referencia.
- Fase 4: ⚠️ el correct% del judge tiene varianza ±10pp — NO sirve como gate
  con n=20. Antes de medir Fase 4: majority voting del judge (3 pasadas) o
  targeted re-runs por pregunta con verdicts razonados leídos a mano.
- Fase 5: demo end-to-end: cuota visible, 429 al excederla, ledger consultable.

## Deuda operativa anotada (no bloquea, no olvidar)

- [x] Limpiar filas muertas de corpus viejos en la DB — HECHO 2026-07-12: 5836
      filas borradas (v1.x, v2.0.0, v2.1.0, husk v2.2.0, experimentos v2.3.x);
      `corpus_chunks` = solo v2.2.1 (2128).
- [ ] Log `query.complete` engañoso: reporta `llm_model or gemini_model` — dice
      gpt-oss-120b aunque genere Gemini.
- [ ] `_hyde_gemini`/`_hyde_openai_compat` tragan excepciones sin loguear — un
      `logger.warning` habría delatado el bug del timeout días antes.
- [x] Commitear este archivo (entró con la PR de la maquinaria 3.8).
