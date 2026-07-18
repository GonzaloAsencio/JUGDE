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
| Modelo (main, prod) | **Groq `llama-3.3-70b-versatile`** vía `openai_compat` (verificado en logs del Space 2026-07-13; el doc decía gemini-flash-lite y estaba desactualizado — Google retiró el free tier de 2.0-flash y prod migró a Groq) |
| Modelo (hard routing) | `gemini-3.5-flash` (thinking), provider Gemini propio e independiente del main — requiere `GEMINI_API_KEY` (fail-closed al arrancar si falta con el flag on) |
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

> Construida entera el 2026-07-14 (PRs #69/#70/#71, todas flag-off), después de
> que **dos corridas de eval agotaran la cuota gratuita de Gemini** — la señal
> concreta de que el free tier es frágil. Dos ítems del plan murieron por probe
> ANTES de escribirse: la disciplina de "medir primero" se pagó sola.

### 2.1 ~~HyDE adaptativo por umbral de coseno~~ ❌ MUERTA POR MEDICIÓN (2026-07-14)
La idea era: correr el brazo crudo primero y saltear HyDE si el mejor coseno ≥
~0.75. **El coseno crudo no discrimina si el retrieval encontró la regla gold.**
Medido sobre el eval set (gratis, sin LLM):
- eval-037: coseno **0.7007** (2º más alto de 40) → gold **fuera del top-15**.
- eval-010: coseno **0.5277** (el más bajo) → gold en **rank 1**.
- Las distribuciones hit/miss se solapan casi por completo (medianas 0.669 vs
  0.617, ambas en ~0.53-0.75). El máximo absoluto del set es 0.7485.
- Umbral ≥0.75 (el que proponía el plan) → saltea HyDE en **0/40** preguntas:
  ahorro cero, la feature sería un no-op. Umbral bajo (~0.65) → le saca HyDE
  justo a eval-015/017/026/030/037, las que más lo necesitan. No hay corte
  defendible.

**Reemplazo que SÍ ahorra (implementado, #70, flag off):** una query ruteada
**descarta su retrieval** (`chunks = stuffed`), así que el brazo HyDE que acaba
de pagar se tira sin leer. `skip_hyde_when_routed` predice el ruteo ANTES del
retrieval (posible ahora que `_detect_entities` corre al frente) y no hace la
llamada. **Una llamada LLM menos por query hard**, sin tocar la respuesta.
Único costo: `semantic_confidence` de una query ruteada pasa a calcularse solo
con el brazo crudo (número ya de significado dudoso en ruteadas) — por eso el flag.

**GATE DE FLIP — regla pre-comprometida (2026-07-18, registrada ANTES de correr):**
El flag NO cambia lo que el modelo responde en ninguna query por construcción
(las ruteadas usan contexto stuffed con o sin HyDE; las no-ruteadas nunca
saltean), así que un A/B de eval completo solo mediría ruido de judge. Lo que sí
puede fallar es el MECANISMO, y eso es deterministicamente medible:
1. **Identidad de predicción** (la claim central): `will_route` pre-retrieval ==
   decisión real post-retrieval en TODAS las evaluables. **Cualquier divergencia
   MATA el flag**: un falso positivo le saca el brazo HyDE a una query que SÍ usa
   su retrieval (degradación de contexto real); un falso negativo prueba que la
   claim de identidad del diseño es falsa. Cero LLM.
2. **Ahorro real**: # llamadas HyDE evitadas == # ruteadas (esperado 21/40).
   **MATA si el ahorro es 0** (no-op). Cero LLM.
3. **Delta de confidence en ruteadas** (raw-only vs fusionado): requiere el brazo
   HyDE real → ~21 llamadas al main (Cerebras), CERO Gemini. Sin condición de
   muerte salvo: **una caída > 0.2 en alguna ruteada** (visible al usuario)
   manda el hallazgo a decisión humana antes del flip. `confidence == 0.0`
   (el único umbral conductual: cache-skip) es inalcanzable por esta vía —
   requiere citations vacías y las citations ruteadas salen del stuffed.
Predicción registrada: identidad 40/40 (misma función `should_route`; la única
divergencia documentada es stuffing roto = deploy roto), ahorro 21/40, deltas
de confidence chicos (mediana < 0.05, raw-only ≤ fusionado siempre que la
fusión tome el mejor coseno).

**RESULTADO (2026-07-18, `scripts/hyde_skip_probe.py`): ✅ EL FLAG VIVE — el
primero de Fase 2 que sobrevive a su gate.**
- Claim 1: identidad **40/40**, cero mismatches, cero stuffing degradado.
- Claim 2: ahorro **21/40** (una llamada HyDE menos por query hard).
- Claim 3: deltas **mediana +0.0000, max +0.0041** (eval-019 y eval-033, los
  únicos no-cero). El costo que motivó el flag es casi inexistente: el mejor
  coseno del pool viene casi siempre del brazo crudo. Brazo HyDE real:
  gpt-oss-120b (config de prod), CERO Gemini gastada.
- Predicción: 3/3 (identidad, ahorro y magnitud de deltas — todas acertadas).
- [ ] **FLIP PENDIENTE (acción de usuario)**: `SKIP_HYDE_WHEN_ROUTED=true` en
  el Space de HF; verificable por logs (`query.routed_hard` sin llamada HyDE
  previa). El flag queda flip-ready; el gate ya no lo bloquea.

### 2.2 Modelo liviano para HyDE — ✅ IMPLEMENTADO (#70, flag off)
El pasaje HyDE son 2-3 oraciones descartables que sólo se embeben, nunca se
muestran. No necesita el modelo de respuesta.
- [x] Setting `hyde_model`; sin setear → cae al modelo principal (byte-idéntico).
- [x] Test que fija que el modelo barato NO puede filtrarse al camino de respuesta.

### 2.3 Cache semántico — ✅ IMPLEMENTADO, PERO SÓLO PARA QUERIES NO-HARD (#69, flag off)
El cache exacto es SHA-256, así que toda paráfrasis paga una llamada LLM entera.
Postgres guarda `embedding → cache_key` (migración 007, HNSW); la RESPUESTA sigue
en Redis. Un hit semántico = lookup de puntero + GET normal. Cuesta un embed
local, cero LLM.

**El probe (`scripts/semantic_cache_probe.py`) mató la versión global de la
feature y le dio forma a la que sobrevivió.** Encontró un par adversarial DENTRO
del propio eval set:
- eval-013: *"...juego Tideturner **en el turno de mi oponente**"* → **SÍ**
- eval-014: *"...juego Tideturner **en mi propio turno**"* → **NO**
- **Coseno: 0.982.** Dos palabras de diferencia, rulings **opuestos** (383.3.d.1
  cuelga toda la respuesta de quién es el turn player).

Con techo 0.982 y piso de paráfrasis 0.874, **no existe umbral que sea a la vez
seguro y útil**: la banda es vacía. Un cache semántico global en este dominio
sirve rulings equivocados, punto.

Restringido a preguntas **no-hard** el techo se derrumba a **0.763** contra el
mismo piso 0.874 → banda amplia. No es suerte: las preguntas de reglas se juegan
en micro-detalles discriminativos (de quién es el turno, qué zona, ready vs
exhausted) que el embedding aplana — y esos detalles son exactamente lo que hace
hard a una pregunta. Así que `is_hard_query`, que ya existía para rutear al
thinking model, **hace de gate de seguridad del cache**: las hard no se sirven
NI se guardan.
- [x] Umbral default **0.85**, dentro de una banda MEDIDA, no adivinada.
- [x] Namespace: el ANN filtra corpus_version + prompt_version + directive_key.
- [x] Frescura + auto-sanación de punteros que Redis evictó antes de tiempo.
- [ ] Gate de eval: hit rate ↑ con **cero** falsos positivos leídos a mano.

### 2.4 ~~Paralelizar los brazos de retrieval~~ ❌ DESCARTADA (2026-07-14)
Mutuamente excluyente con 2.1: paralelizar obliga a llamar SIEMPRE a HyDE
(ahorra ~1s), mientras que el objetivo real es NO llamarlo (ahorra cuota). La
cuota es el dolor; ganó 2.1. Reconsiderar sólo si la latencia pasa a ser el
cuello de botella y la cuota deja de serlo.

### 2.5 Streaming SSE (latencia percibida)
Ya identificado en FUTURE_WORK como short-term. Con respuestas que llevan un
Reasoning largo, el time-to-first-token importa más que el p50 total — es la
mejora de UX más rentable pendiente.
- [ ] Stream de la respuesta del LLM vía Server-Sent Events desde FastAPI,
      consumido en el frontend Next.
- [ ] Resolver la pieza bloqueante ya anotada: las respuestas cacheadas también
      deben "streamear" (no aparecer instantáneas) para no generar un salto de UX.

### 2.6 ~~Acotar el Reasoning en preguntas simples~~ ❌ MUERTA POR GATE (2026-07-17, strippeada 2026-07-18)
El "Reasoning:" obligatorio (regla 7) es lo que levanta el bucket hard, pero en
un lookup de una sola regla paga tokens de salida — el lado caro — para repetir
lo obvio. Se tomó la variante que el propio plan sugería como alternativa
(reasoning largo sólo donde hace falta), no el "máximo 3 bullets" a secas.
- [x] `_CONCISE_REASONING`: cap de 3 bullets en queries **ni ruteadas ni
      scaffoldeadas**. ACOTA, nunca elimina — sacar el Reasoning desharía los
      few-shots de encadenamiento (v6/v7) y rompería el parseo de `Answer:`.
- [x] Exclusiones fijadas por test: `needs_scaffold()` gana; las ruteadas nunca
      lo reciben (fueron al thinking model justamente porque necesitan razonar).
- [x] Namespace de cache propio (`+concise`, como `+hard-routing`): una respuesta
      concisa y una verbosa nunca colisionan. Sufijar en vez de bumpear
      `prompt_version` deja la key flag-off byte-idéntica.
- [x] **GATE DE FLIP CORRIDO (2026-07-17): ❌ EL FLAG MUERE.** Regla
      pre-comprometida: cero regresiones de veredicto en el subconjunto estable
      Y longitud de respuesta abajo. Universo: las 13 que el flag MUEVE
      (determinista: 21 ruteadas nunca ven el cap, 6 scaffoldeadas las gana el
      scaffold — ambos por construcción testeada). Brazos OFF/ON hoy, config de
      prod (gpt-oss-120b/8192), mismo judge.
      - Longitud: mediana **856 → 588 (-31%)** ✅ — el ahorro es real.
      - Veredictos: **eval-001 regresó correct→partial y es REAL** (correct 3/3
        en OFF por protocolo de estabilidad). Mecanismo: el judge señala que
        OMITIÓ el límite del Chosen Champion — el cap recortó contenido de la
        RESPUESTA pese a que el prompt lo prohíbe explícitamente. El riesgo
        anotado arriba, materializado.
      - eval-030 también cayó pero flippeó en las re-corridas OFF → INESTABLE,
        excluida (la lista de inestables crece a eval-016/018/030 — 3 de las 13
        movidas).
      - Predicción registrada antes de correr: longitud baja (✅ alta
        confianza); "si algo cae será eval-005 o eval-030" — eval-030 cayó pero
        resultó inestable; eval-001 NO estaba en la lista. Media predicción.
      **Queda espacio para un v2** (el mecanismo es prompt-fixeable: reforzar la
      protección del Answer), pero es un lever NUEVO con su propio gate.
- [x] **Strip ejecutado (2026-07-18)**: `concise_reasoning` fuera de config,
      `_CONCISE_REASONING` fuera de generation, el `elif` y el sufijo `+concise`
      fuera de pipeline, `test_concise_reasoning.py` borrado, pins removidos
      (regla de cero código muerto, mismo trato que 3.11.1a).

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

### 3.11 Los 4 gaps reales de contexto (2026-07-16, post-arreglo del probe)

Con `retrieval_probe` midiendo el contexto que producción ARMA (ver Fase 6.1), el
baseline honesto es **22/26 (85%)** de las evaluables con TODOS sus gold refs en
el contexto de generación. El bucket ruteado está limpio (**12/12**). Los 4 gaps
reales están todos en el bucket **no-ruteado**, y no comparten causa conocida —
tratarlos como una familia sería repetir el error del "gap 383":

| Pregunta | Falta | Perfil |
|---|---|---|
| eval-020 | `383.3.d` | 1 de 2 refs. `816` entra en rank 1 y lo tapaba |
| eval-030 | `365.1` | 1 de 3 refs. `809.1.a` llega por family completion |
| eval-037 | `131.4`, `425` | 2 de 3 refs |
| eval-039 | `347.3`, `348` | 2 de 2 refs — contexto sin NADA del gold |

- [x] **3.11.0 ✅ Triage — HECHO (2026-07-16). VEREDICTO: NO comparten mecanismo.**

**Primero hubo que arreglar la herramienta de triage** (no se pudo cumplir el
"cero código"): `miss_diagnosis.py` filtraba con `first_covering_rank` (regla
ANY-ref) y hacía `continue` si CUALQUIER ref se recuperaba → **eval-020 (`816` en
rank 1) y eval-030 (`809.1` en rank 12) NUNCA fueron diagnosticadas**. La
herramienta cuyo trabajo es elegir el lever era ciega a 2 de los 4 gaps. Tercer
instrumento con la misma mentira. Ahora diagnostica **por REF FALTANTE** (la
unidad correcta) contra el contexto real, y clasifica cada ref por separado — un
hermano de OTRO gold ref ya no rescata el veredicto de éste.

**Resultado: 6 refs faltantes en 4 preguntas. Los 6 chunks gold ESTÁN en el corpus
→ los 6 son gaps de retrieval, ninguno de corpus.**

| Pregunta | Ref | Clase | Lever |
|---|---|---|---|
| eval-020 | `383.3.d` | **A: granularidad** | chunk lineage |
| eval-030 | `365.1` | B: gap semántico | puente de vocabulario |
| eval-037 | `131.4`, `425` | B: gap semántico | puente de vocabulario |
| eval-039 | `347.3`, `348` | B: gap semántico | puente de vocabulario |

**1 A + 5 B → se atacan por separado.** Confirmado el gate: no hay familia que
inventar.

**eval-020 (A) — el hallazgo que cambia su lever.** Su vector top-15 trae
`[1] 816. Temporary` y **`[4]` y `[6]` de `383. Triggered Abilities`**. La familia
383 YA ESTÁ EN EL CONTEXTO; lo que falta es el chunk hermano que lleva
`383.3.d` — y vive en la MISMA sección. No es gap semántico: es lineage. Y explica
por qué "trigger" como keyword murió ayer: `_complete_keyword_families` exige que
la familia la nomine un **keyword TAGEADO** (`kw_sections` sale de `auto_chunks` =
`tagged_lookup`), no le alcanza con que la familia esté en contexto por el arm
vectorial. **La compuerta pide la puerta equivocada.** → El lever de 020 es
completar la familia de una sección de regla YA presente en el contexto, sin
compuerta de keyword. **Esto DESPLAZA al lead FTS de 6.2 para esta pregunta**
(seguía sirviendo, pero el lineage es más directo y de menor blast radius).

**eval-039 (B) — el perfil opuesto, y una advertencia.** Gold en `341. Showdowns`;
se recupera `649. Conceding`, `339. Step 3: Pass`, `338. Step 2: Execute` — nada de
la familia 347/348. Causa: **la pregunta dice "pass priority", la regla dice
"Focus"**. Desajuste de vocabulario puro. Es EXACTAMENTE el perfil por el que murió
3.6 ("los términos ganadores NO están en la pregunta") → **el arm FTS-keyword
probablemente tampoco lo salve**. Antes de construir nada para los B, medir si
existe algún término extraíble de la pregunta que alcance el gold. Si no existe,
los B son puente de vocabulario (HyDE / fine-tuning 3.9), no keyword.
### 3.11.1 eval-020 (clase A: lineage)

#### (d) ~~Nominar la familia desde las secciones de regla del contexto~~ ❌ MUERTA POR GATE (2026-07-16, cero código de producto)

El triage la señalaba como favorita: `383. Triggered Abilities` ya entra en rank
4 y 6, solo falta el hermano con `383.3.d`. Se gateó con
`scripts/family_nomination_probe.py` (CONTROL = producción hoy; TREATMENT = misma
completion pero nominada por las secciones de regla del contexto). Ambos brazos
usan `_retrieve`, `family_lookup` y `_complete_keyword_families` REALES; el
TREATMENT se arma sobre un contexto con la completion APAGADA y se completa UNA
sola vez al mismo cap, para no apilar dos colas y inflar el resultado.

**Resultado: PIERDE 1W/1L.**

| | |
|---|---|
| GANA | eval-020 suma `383.3.d` ✅ |
| **PIERDE** | **eval-030 pierde `809.1` Y `809.1.a`** ❌ |
| Costo | contexto 152 → **247 chunks (+62%)**, creció en **14/14** preguntas |

**La trampa que el gate cazó y el titular tapaba:** la métrica principal MEJORA
(22/26 → 23/26), porque eval-030 ya estaba rota por `365.1` y perder dos refs más
no le mueve el `fully_covered`. **Gateando sobre el neto, esto pasaba como
victoria y shippeaba una regresión.** El gate decía "sin sacar ningún gold ref a
las otras 25", no "mejora el neto". Por eso existe.

**Mecanismo de la pérdida — NO es el append-only roto:** es **dilución del cap**.
Al nominar varias familias, todas compiten por los mismos 8 slots, y `_FAMILY_SQL`
ordena `BY content` a través de TODAS las secciones: `"### 365..."` ordena antes
que `"### 809..."`, así que las familias de número bajo se comen el presupuesto y
Deflect queda afuera. En CONTROL la nominación era solo Deflect y sus 3 chunks
entraban cómodos. **Ensanchar la nominación sin ensanchar el presupuesto es un
juego de suma cero.**

**Por qué no se barren umbrales (regla de 3.8):** con 26 preguntas, probar caps
hasta que uno gane es fitear ruido. Y el costo lo condena igual: **+62% de
contexto en TODAS las preguntas para ganar UNA**. Aunque se arreglara la dilución
(cap por familia, round-robin), el trade sigue siendo malo.

#### (a) Relajar el umbral a 1 carta + 1 keyword — ✅ **GANA EL GATE DE RETRIEVAL** (2026-07-16, cero código de producto)

Gateado con `scripts/routing_threshold_probe.py`. CONTROL = `is_hard_query`
shippeado; TREATMENT = misma función con la rama carta+keyword relajada a
`keyword_count >= 1`. **La exigencia de carta SE MANTIENE** — `routing.py` es
explícito: el vocabulario de keywords tiene palabras cotidianas (draw, discard,
token, combat), así que relajar sin carta mandaría "¿cuándo robo?" al modelo
thinking. Un test pinea que el delta es EXACTAMENTE la celda (1 carta, 1 keyword)
y ninguna otra.

**Resultado: 3W / 0L.**

| | |
|---|---|
| GANA | eval-020 `383.3.d`, eval-030 `365.1`, eval-037 `131.4`+`425` |
| PIERDE | **nada** |
| Cobertura | 22/26 → **25/26** |

**Cierra 3 de los 4 gaps**, no solo el que motivó el ítem. `eval-010` (única con
gold en errata, que el rulebook stuffeado NO lleva) no se mueve: no detecta
cartas y el umbral sigue exigiéndola — el riesgo identificado antes de correr no
se materializó.

Señal de que el mecanismo es sano, no un artefacto: las 6 que empiezan a rutear
tienen keywords `hidden`, `showdown`, `temporary`, `deflect`, `repeat` — mecánicas
reales, no palabras cotidianas. "1 carta + 1 mecánica" ES una pregunta de
interacción.

**COSTO — decisión humana, no auto-ship:**
- **routing 21/40 → 27/40** (52% → 67% del set). 6 nuevas al modelo thinking.
- 3 de esas 6 (eval-016/018/032) **no tienen gold ref**: pagan latencia y cuota
  sin beneficio medible acá.
- gemini-3.5-flash: **~25-35s** por consulta y **~20 req/día** de free tier. Hoy
  mismo saltó `llm.rate_limited` con 2 preguntas. Esto empeora ~30% un problema
  que YA existe a 52%.
- ⚠️ **El eval NO es tráfico real**: está enriquecido con preguntas hard, así que
  "67% del eval rutea" ≠ "67% de prod rutea". No extrapolar (lección del día).

**Lo que este gate NO prueba:** mide PRESENCIA EN CONTEXTO, no que el LLM
responda bien. eval-020 con `383.3.d` en contexto ≠ eval-020 correcta. Falta el
gate de generación, que necesita cuota.

- [x] **Siguiente paso (two-step, método de la casa):** implementado flag-off →
      corrido el gate de generación (2026-07-17) → **NO se flipea. Ver abajo.**

#### GATE DE GENERACIÓN — ❌ **EL FLAG MUERE. 0W / 2L** (2026-07-17)

El lever que ganó retrieval 3W/0L **pierde generación 0W/2L**. Flag queda OFF.

**El gate se corrió sobre 6 preguntas, no sobre las 3 del titular.** El flag mueve
el routing 21/40 → 27/40: las 6 que cruzan son el universo. Gatear sobre las 3
con gold ref era mirar el recorte que solo puede ganar — la forma exacta del
lever (d) y del arm fusionado de 3.11.2. Tres de las seis (eval-016/018/032) no
tienen gold ref pero **sí reciben veredicto del judge**: `rule_reference` gatea
el recall, no el juicio. Ya estaban correctas: solo podían romperse.

| id | CONTROL (flag OFF) | TREATMENT (flag ON) | |
|---|---|---|---|
| eval-020 | wrong | wrong | = |
| eval-037 | wrong | wrong | = |
| eval-030 | correct | correct | = |
| eval-032 | correct | correct | = |
| **eval-016** | **correct** | **wrong** | ❌ **REGRESIÓN** |
| **eval-018** | **correct** | **wrong** | ❌ **REGRESIÓN** |

Ambos brazos corridos hoy, mismo código (rama `feat/routing-threshold-relaxed`,
stack #69→#74, resto de flags OFF), corpus v2.2.1. El baseline del 15/07 NO se
usó de control: otro stack, dos días viejo.

**Corrección al titular de (a):** el gate de retrieval contaba 3W, pero
**eval-030 ya se contestaba bien**. Ganar un gold ref en una pregunta que ya
acertás vale cero en generación. El upside real sobre el eval set eran **dos**
preguntas (eval-020, eval-037), y no ganó ninguna.

**El mecanismo — el rulebook stuffeado no ayuda, ESTORBA:** eval-016 y eval-037
dispararon `query.no_info_despite_context` con `confidence=0.0`. Con el rulebook
COMPLETO en contexto, el modelo contestó *"I don't have enough information"*.
eval-016 bajo CONTROL citaba `811.1.b` y `811.1.c.3` y acertaba; con todo el
rulebook adelante, se rindió. eval-037 empeoró incluso quedándose en `wrong`:
bajo CONTROL al menos razonaba desde 820, bajo TREATMENT no contestó nada.

**⚠️ CONFOUND — el gate NO identifica el mecanismo.** El TREATMENT cambia DOS
cosas a la vez: el contexto (RAG → rulebook stuffeado) **y** el modelo
(`gemini-flash-lite-latest` → `gemini-3.5-flash`). La regresión puede ser del
contexto, del modelo, o de los dos. El gate responde la pregunta de shipping
("¿flipeamos?" → NO, sin ambigüedad) y NADA más. No leer "el rulebook stuffeado
diluye" como probado: no lo está.

> **Corrección (2026-07-17).** La primera redacción de este bloque decía que el
> CONTROL corrió en `gpt-oss-120b`. **Falso, y leído del log.** Con
> `llm_provider='gemini'`, `create_provider` devuelve
> `GeminiProvider(model=settings.gemini_model)` = `gemini-flash-lite-latest`;
> `gpt-oss-120b` (`llm_model`) NO lo toca ese provider. La telemetría de
> `pipeline.py` re-deriva el modelo de `settings` en vez de preguntárselo al
> provider que generó, y miente. Ver "Bug de telemetría" abajo.

**Predicción registrada antes de correr: FALLÓ.** Se predijo que eval-037 ganaba
(confianza media-alta) con mecanismo identificado: su respuesta razonaba desde
820.1/820.3.a/820.1.d — todo 820 — sin ver 131.4 ni 425, así que meterlas debía
alcanzar. Con las dos reglas en contexto, contestó "no tengo información
suficiente". **Presencia en contexto ≠ corrección, y esta vez la presencia
empeoró la respuesta.** Es la tercera vez en tres días que una métrica proxy
sana esconde una pérdida real.

**Artefacto descartado, NO es un hallazgo:** el reporte del brazo TREATMENT dice
`Retrieval recall: 0/3 = 0%` contra 3/3 del CONTROL. No es regresión.
`_build_citations` deja `rule_codes=[]` para `RULEBOOK_CHUNK_ID` a propósito
(derivarlos listaría cada código del juego = paper hit garantizado), así que una
pregunta ruteada **no puede** puntuar recall por construcción. La métrica de
recall del eval es ciega al bucket ruteado — por eso existe el probe de
retrieval, que mide presencia en contexto directo y no vía citations.

**🔴 LEAD para 4.2/4.3 — es un LEAD, NO un resultado.** `hard_query_routing` está
**ON hoy** (default `True`, y `HARD_QUERY_ROUTING=true` en `.env`): 21/40 del
eval ya rutean. Si el camino ruteado puede convertir una respuesta correcta en
"no tengo información", la pregunta abierta es si el routing YA shippeado está
lastimando preguntas que se contestaban bien sin él. Medido acá: 2 de 4 correctas
se rompieron al rutear. **6 preguntas no prueban nada sobre las 21.**

#### Aislamiento del confound (2026-07-17) — el CONTEXTO es el culpable, al menos una vez

Se corrió la celda faltante: **contexto RAG + el modelo, presupuesto y timeout
EXACTOS del brazo ruteado**, dejando el contexto como única variable.

| eval-016 | contexto RAG | rulebook stuffeado |
|---|---|---|
| `flash-lite`, 1024 tok | correct | — |
| `gemini-3.5-flash`, 8192 tok, 90s | ✅ **correct** | ❌ **wrong** (`no_info_despite_context`) |

**Mismo modelo, mismo presupuesto de salida, mismo timeout. Solo cambia el
contexto.** Con RAG acierta; con el rulebook COMPLETO contesta "I don't have
enough information". **El modelo queda exonerado para eval-016: el rulebook
stuffeado es lo que rompe.** Es una sola pregunta — no generaliza a las 21 — pero
el confound está muerto para ella y el mecanismo pasó de hipótesis a observado.

**eval-018 — MEDIDA al tercer intento (mismo día, los 503 eran transitorios):**
`gemini-3.5-flash` + RAG (8192 tok, 90s) → **"I don't have enough information"**.
A diferencia de eval-016, acá el contexto NO exonera al modelo: 3.5-flash falla
eval-018 con CUALQUIER contexto (con RAG se rinde, con el stuffed inventó
healing), mientras flash-lite la contestaba (inestable: correct/partial entre
corridas). Mecanismo distinto al de eval-016 — el modelo está implicado.
Consistente con §3.13: eval-018 es una pregunta inestable/difícil, no un efecto
puro del stuffing.

**⚠️ Trampa metodológica que casi se come este experimento.** El primer intento
de la celda del medio corrió `gemini-3.5-flash` con `max_output_tokens=1024` (el
presupuesto del provider MAIN) y dio `partial/partial`, que se leyó como "el
modelo también degrada". **Era truncamiento, no razonamiento**: el judge dijo
literal *"the answer begins to cite Evelynn's text but is cut off"*. El propio
`config.py` lo advierte tres líneas arriba: *"Thinking models spend the output
budget on thoughts; 1024 strangles them"* — por eso `hard_max_output_tokens=8192`.
Aislar el contexto exige clonar **todo** lo demás del brazo ruteado (modelo,
tokens, timeout), no solo el modelo. Un brazo de control a medio clonar fabrica
el resultado que uno fue a buscar.

**Próximo paso del lead:** mismo aislamiento sobre las que YA rutean hoy (no las
6 del flag), con `gemini-3.5-flash` estable. Si el patrón se repite, 4.2/4.3
necesita revisión — está ON en producción.

#### 🐛 Bug de telemetría — `query.complete` reporta un modelo que nunca corrió

Encontrado mientras se diseñaba el aislamiento. **Pre-existente desde `fc8e3ee`
(2026-07-02), no lo introdujo esta rama.**

`pipeline.py` re-deriva el modelo para el log en vez de preguntárselo al provider
que generó:

```python
model = settings.hard_gemini_model if routed else (settings.llm_model or settings.gemini_model)
...
answer = _generate_guarded(hard_provider if routed else provider, ...)   # el provider decide
```

Con `llm_provider='gemini'`, `create_provider` devuelve
`GeminiProvider(model=settings.gemini_model)` → corre `gemini-flash-lite-latest`.
Pero la telemetría reporta `llm_model` → **`gpt-oss-120b`**, un modelo que ese
provider **nunca toca**. Todo log de query no ruteada miente sobre el modelo
mientras `llm_provider != 'openai_compat'` y `llm_model` esté seteado.

Radio de daño: solo `structlog` (`query.complete`); el schema de respuesta de la
API no lleva `model`. Pero es exactamente la enfermedad de la casa — el
instrumento mintiendo — y ya costó una lectura errónea del gate de hoy.

**Fix de raíz:** el provider es la autoridad sobre su propio modelo. Exponer
`model` en `LLMProvider` y loguear `(hard_provider if routed else provider).model`,
una sola copia, imposible de driftear. Hoy ninguno de los dos providers lo expone
(`self._model` es privado) y hay ~10 stubs que tendrían que declararlo — cambio
chico pero transversal, no se metió en esta rama.

**Config local a revisar (aparte):** `.env` tiene `llm_provider='gemini'` pero
también `llm_model='gpt-oss-120b'` y `llm_base_url='https://api.cerebras.ai/v1'`
seteados — los dos últimos solo los usa `openai_compat`. Parece un switch a medio
hacer. Determina qué modelo mide el eval, así que decidir cuál es el main real
antes del próximo gate.

### 3.12 Modelo MAIN: `flash-lite` vs `gpt-oss-120b` (2026-07-17)

**gpt-oss-120b gana 4W / 0L. 11/19 → 15/19 correctas.**

Primera medición cabeza a cabeza de los dos main en este repo. Ninguna corrida
anterior sirve de baseline: todas están atribuidas a un modelo que se infirió de
un log que mentía (ver bug de telemetría arriba, arreglado en `f0c8b94`).

**Universo: las 19 que el MAIN sirve.** Calculadas con `routing_decision`
(`routing_enabled=True`, `relaxed=False`) → 21 ruteadas / 19 no. Coincide exacto
con el 21/40 que el plan venía citando. Las 21 ruteadas no entran: las sirve
`gemini-3.5-flash` y el main no las toca.

Los dos brazos verificados vía `create_provider(s).model` ANTES de gastar, no vía
log — la lección del día.

| | flash-lite | gpt-oss-120b |
|---|---|---|
| correct | 11 | **15** |
| partial | 3 | 1 |
| wrong | 5 | 3 |

Sobre las 17 comparables a presupuesto igual: **B gana 4 (eval-005, eval-008,
eval-012, eval-032), pierde 0.** Cuatro victorias sin regresión sobre 17 supera
el umbral de ruido fijado antes de mirar (1-2 preguntas sobre 19 = no
distinguible; el judge es no determinista).

**⚠️ REQUISITO DE DEPLOY, no un tune opcional: `gpt-oss-120b` es un modelo de
RAZONAMIENTO.** Con `max_output_tokens=1024` devolvió **null content en 2/19**
(eval-016, eval-037) — el mismo `"1024 strangles them"` que `config.py` advierte
para el modelo hard. Con 8192 las dos contestan (mal las dos, igual que
flash-lite, así que el 4W/0L no se mueve). Ojo: `max_output_tokens` es COMPARTIDO
entre los dos providers ("Applies to both providers"), así que subirlo para
gpt-oss también se lo sube a flash-lite — no medido.

**Artefacto descartado, NO es del modelo:** el brazo B promedió 18.5s vs 7.5s,
con cuatro preguntas clavadas en ~60s. **Era throttling de Cerebras por tirarle
19 requests seguidos**, no el modelo razonando. Corrida sola, eval-003 tarda
**11.9s** contra los 56.5s de la ráfaga. La latencia real es ~2x flash-lite
(11.9s vs 5.3s), no 2.5x. El retry de `_completion_with_retry` solo cubre 429 con
backoff acotado, y ese backoff es lo que infló el promedio.

**Predicción fallida (mía):** se predijo latencia "mucho menor" en B porque
Cerebras es rápido. **Al revés: gpt-oss-120b es ~2x MÁS LENTO por request.** Más
preciso y más lento, no más preciso y más rápido.

**Lo que esta medición NO contesta:**
- **Qué corre en prod.** Sigue invisible hasta deployar `f0c8b94` y curlear
  `/health`. Si prod es `llm_provider=gemini` + `llm_model=gpt-oss-120b`, prod
  corre **flash-lite** y gpt-oss-120b NUNCA corrió ahí — el switch no toma efecto
  porque `create_provider` ignora `llm_model` bajo gemini.
- **Los límites de cada tier**, que era el motivo original del switcheo. Eje
  operativo, no lo mide el eval. Dato suelto: Cerebras throttleó a los ~19
  requests en ráfaga.

> **RESPONDIDO (2026-07-17, post-merge de la pila).** Primer curl a
> `/health` del Space con `f0c8b94` deployado:
>
> ```json
> "models": {"main": "llama-3.3-70b-versatile", "hard": "gemini-3.5-flash"}
> ```
>
> **El main de prod es `llama-3.3-70b-versatile`** (Groq, vía openai_compat) —
> un TERCER modelo que ninguno de los dos brazos de 3.12 midió. Ni la hipótesis
> "prod corre flash-lite" ni la creencia "lo cambié a gpt-oss-120b" eran
> ciertas: el env del Space difiere del `.env` local. Consecuencias:
> - El 4W/0L de gpt-oss-120b es contra flash-lite, **no contra el main real de
>   prod**. Decidir un cambio del main de prod requiere el tercer brazo:
>   `llama-3.3-70b-versatile` sobre las mismas 19.
> - El CONTROL del gate 3.11.1a (flash-lite) tampoco es el main de prod. El
>   veredicto del gate (no flipear `relaxed`) se sostiene igual — perdió contra
>   SU propio control y el default seguro coincide — pero su baseline no
>   describe prod.
> - Los comentarios del repo ("prod runs Groq/openai_compat as main") tenían
>   razón; el `.env` local era el desviado.

### 3.13 Re-triage de gaps bajo el main nuevo (2026-07-17, cero cuota)

`miss_diagnosis` (determinista, HyDE off) da **idéntico** al pre-flip — 6 refs
faltantes en 4 preguntas — porque el retrieval no depende del main. Lo que
cambió es el cruce con los VEREDICTOS de gpt-oss-120b:

| id | veredicto (gpt-oss) | refs faltantes | lectura |
|---|---|---|---|
| eval-030 | **correct** | 365.1 (B) | **YA NO ES GAP**: contesta bien sin el ref |
| eval-039 | **correct** | 347.3, 348 (B) | **YA NO ES GAP**: ídem |
| eval-020 | partial | 383.3.d (A:granularity) | gap real; el modelo lo subió de wrong a partial |
| eval-037 | wrong | 131.4, 425 (B:semantic) | **el gap más firme**: faltan refs Y contesta mal |
| eval-016 | wrong | (sin gold ref) | NO diagnosticable por refs — ver abajo |
| eval-018 | wrong | (sin gold ref) | ídem |

**El modelo curó dos "gaps de retrieval" sin tocar el retrieval.** eval-030 y
eval-039 siguen sin sus refs en contexto y contestan bien igual — el pre-gate
3.11.2b condicionado de ayer ("refs B de eval-030/037") queda re-scopeado a
**solo eval-037**.

**eval-016 y eval-018 son INESTABLES, no gaps**: bajo flash-lite mismo-config
flippearon correct→wrong y correct→partial entre la corrida de la mañana y la
de la tarde. Sin gold refs no hay señal determinista; atacarlas requiere primero
medir su estabilidad (N corridas) o mejorar sus canonical answers — un lever de
eval-set, no de retrieval.

Caveat honesto: miss_diagnosis corre HyDE-off, y el brazo HyDE de producción
ahora escribe pasajes con gpt-oss (el main cambió) — el diagnóstico es un piso,
no una predicción exacta.

**Cola de ataque resultante**: eval-037 (B:semantic, el "hit de papel" con
mecanismo conocido) > eval-020 (A:granularity, ya partial) > estabilidad de
eval-016/018. Los gates de flip de Fase 2 (#69/#71/#70) van antes que cualquier
lever nuevo.

#### El tercer brazo (2026-07-17, mismo día): `llama-3.3-70b-versatile` — el main REAL de prod — es el PEOR de los tres

Corrido vía Groq con los defaults exactos de prod (1024 tok, 30s), mismas 19,
mismo judge que los otros dos brazos (gpt-oss-120b vía Cerebras — el judge NO se
cambió a mitad de comparación; caveat de auto-preferencia para el brazo B
mitigado leyendo los justificativos a mano).

| | flash-lite | gpt-oss-120b | **llama (PROD)** |
|---|---|---|---|
| correct | 11 | **15** | **9** |
| partial | 3 | 1 | 3 |
| wrong | 5 | 1 (+2 error) | 7 |

**gpt-oss-120b le gana al main de prod 6W/0L** sobre las 17 comparables
(eval-002/005/012/030/039/040). Cuatro de las seis son contradicciones duras de
reglas leídas a mano, no estilo: llama afirma que Deflect taxea desde el trash
(030), que se puede seguir casteando tras doble pass (039), que el conquer de
Kai'sa triggerea en un battlefield ya scoreado (040). Las 2 inválidas
(eval-016/037: null content de gpt-oss a 1024 tok) se saben empate-wrong por la
re-corrida a 8192 — el tally no se mueve.

**Dato incómodo**: eval-030 y eval-039 estaban `correct` en todos los baselines
del día (flash-lite). Bajo el main que prod REALMENTE corre, están `wrong` hoy.

**Recomendación**: mover el main de prod a `gpt-oss-120b` (Cerebras). Cambio de
env del Space: `LLM_BASE_URL=https://api.cerebras.ai/v1`, `LLM_API_KEY=csk-...`,
`LLM_MODEL=gpt-oss-120b`, **más `MAX_OUTPUT_TOKENS=8192`** (requisito, no tune:
es un modelo de razonamiento; a 1024 devuelve null en 2/19). Verificación
post-flip: `curl /health` debe decir `"main": "gpt-oss-120b"`. Latencia: ~2x
flash-lite por request (11.9s suelta); el promedio en ráfaga infla por
throttling de Cerebras (~19 req).
- [x] **(c)** arm FTS sobre keywords extraídos (lead de 6.2) — ❌ **MUERTO POR
      GATE** para eval-039, ver 3.11.2. Sigue sin probar para 030/037.

### 3.11.2 ~~eval-039 (clase B: ¿existe término extraíble?)~~ ❌ MUERTO POR GATE (2026-07-16, cero código)

La única clase B que el lever (a) NO cierra (no nombra carta → `is_hard_query`
no la rutea ni con `relaxed=True`). Gate pre-comprometido y predicción
registrada ANTES de correr; ambos respetados con resultado negativo.

**La hipótesis de entrada era FALSA.** Se sospechaba "dice *pass priority*, la
regla dice *Focus* → no hay término extraíble". Leído del rulebook, la regla
gold 348 dice literal: *"If all players **pass** **Focus** without playing a
**spell**..."*. `pass` y `spell` **están** en la pregunta. Los keywords que
`extract_keywords` produce son `attack, pass, priority, passes, cast, spells,
afterward`, y los dos chunks gold matchean por exactamente **UN** término:
`pass`. El mecanismo real no es "no hay solapamiento" sino **el solapamiento no
DISCRIMINA**: `pass`/`attack`/`priority` están por todo el rulebook y
`ts_rank_cd` entierra un chunk gold corto que carga un solo término común. Es
el mismo mecanismo que mató a 3.6 ("chunks gold chicos pierden por densidad"),
no el que suponíamos.

**Confound medido y descartado:** `_FTS_OR_SQL` usa `to_tsvector('simple')` y
`simple` NO stemea → `spells` (pregunta) no matchea `spell` (gold). Con
`english` el gold pasaría de 1 a 2 términos. Se probó. No alcanza.

| config | FTS rank del gold | fused | regresiones (vector@5 perdidos) |
|---|---|---|---|
| `simple` | **None** | 9 | eval-002, eval-007, eval-008 |
| `english` | **None** | None | eval-002, eval-008, eval-027 |

**Muere dos veces**, y la segunda importa más que la primera:
1. El arm FTS **nunca** trae el gold al top-15, en ninguna config.
2. Bajo `simple` el arm **FUSIONADO** sí lo trae a rank 9 — pero **cuesta 3
   preguntas** que el vector hoy acierta @5. Es la forma exacta del lever (d):
   el titular mejora y esconde la regresión. Gatear sobre el neto habría
   shippeado una pérdida por segunda vez.

**Conclusión:** eval-039 es **puente de vocabulario** (`priority`→`Focus`,
`attack`→`Showdown`). El lever (c) muere para ella. Munición restante: HyDE /
3.9 fine-tuning.

- [ ] **3.11.2b eval-030 / 037 (los otros 4 refs B)** — el lever (a) SÍ los
      cierra (3W/0L en presencia), así que su gate real es el de generación de
      #74, no éste. Si (a) muere ahí, correr este mismo pre-gate para sus refs
      antes de tocar (c): el resultado de eval-039 hace sospechar que el perfil
      se repite, pero **sospechar no es medir**.

**Nota de método:** el número a mover es *presencia del gold en el contexto*, NO
recall@k del arm. El arm sub-reporta a propósito (producción le suma cartas
tagueadas y family completion encima). Y ojo con el piso: el probe corre HyDE off
y producción fusiona un arm HyDE en las no-ruteadas.

### 3.10 Detección de cartas: fix del posesivo + desambiguación (2026-07-15)

Sesión de re-eval sobre `feat/concise-reasoning`. El "57% correct" del primer run
era mentira estadística (7 `error` eran caídas de red/DB, no del sistema); real
**~69% correct / 77% con partials** sobre lo que corrió. Diagnóstico honesto de
los wrong reales, cada uno con causa distinta (no comparten fix):

- **eval-029 → FIX SHIPPEADO** (`538b4e8`). Un nombre de carta en posesivo con
  guion (`"Jhin - Virtuoso's"`) no se detectaba: el guion fuerza el pass subset y
  `_norm_word` convertía el token en `"virtuosos"` (≠ `"virtuoso"`). Se strippea
  el posesivo antes de sacar puntuación. TDD (test rojo→verde, 27/27), verificado
  determinísticamente que Jhin ahora entra al contexto stuffeado (2→3 secciones).
  E2E pendiente de reset de cuota. **Bonus:** cualquier carta en posesivo+guion.
- **eval-028 "Jhin Legend" → abierto.** No es bug del eval-set: "Legend" es el
  TIPO de la carta `Jhin - Virtuoso`. Resolver una referencia por-tipo a la carta
  impresa es un problema aparte (más grande que el posesivo).
- **eval-020 (y 013/014/015/017) → gap semántico sistémico de la familia 383
  "Triggered Abilities".** El sub-rule gold (383.3.d / 383.3.d.1 / 383.4.e) NO
  está ni en el vector top-50. **MEDIDO 2026-07-15 (gratis, HyDE off):** agregar
  "trigger"/"triggered"/"triggers" a `_KNOWN_KEYWORDS` para sembrar la familia vía
  `tagged_lookup` → **0 wins, 0 losses, y el sub-rule sigue ausente en las 5**
  (CONTROL=T2=False). La compuerta de `_complete_keyword_families` exige que un
  chunk de la familia SOBREVIVA el retrieval, y acá no sobrevive → nada que
  completar. Keyword-family muerto para este gap. Necesita el "lever B" real
  (arm FTS-keyword sobre keywords extraídos, inyección de familia sin la
  compuerta, o HyDE mejor). **"trigger" habría sido blast-radius amplio por CERO
  beneficio — validado medir-antes-de-shippear.**
- **eval-005 / eval-034 → razonamiento genuino** (regla presente en contexto,
  modelo concluye mal). Fix vía prompt = mayor blast-radius del pipeline; caza de
  baja probabilidad, se deja para un enfoque de eval más sistemático.

**Ojo metodológico reconfirmado:** `retrieval_hit`/`match_rule_reference` cuenta
un hit si CUALQUIER ref matchea, y una pregunta que erroró queda como recall miss.
Ambos distorsionan. Medir presencia del sub-rule ESPECÍFICO en el contexto de
generación, no el recall de citations.

#### 3.10.1 Desambiguación de carta ("¿te referís a...?") — FUTURA, diseñar aparte
El `@tag` ya garantiza el nombre exacto (camino confiable). `detect_card_mentions`
es el fallback degradado para texto libre/typos. La respuesta correcta a largo
plazo para el camino degradado: cuando la mención es ambigua ("Jhin" = 3
impresiones) o un typo ("Jihn Virtouso"), **mostrar candidatos y que el usuario
elija**, en vez de responder en silencio con la carta equivocada o ausente.

Menos complejo de lo que parece:
- [ ] La señal de ambigüedad YA EXISTE: `entities.ambiguous_champion_count`
      (`pipeline.py::_retrieve`) — hoy se computa y se descarta.
- [ ] Candidatos para typos = **determinístico, NO IA**: `pg_trgm` (similitud de
      trigramas) contra la vocab de cartas. Más seguro y barato que hacer razonar
      al modelo.
- [ ] Re-consulta ya resuelta: la selección vuelve como `@tag` → `tagged_lookup`.
- [ ] Lo que falta es producto/UX: (1) generación de candidatos vía pg_trgm,
      (2) nuevo estado de respuesta de la API ("necesita desambiguación" + candidatos),
      (3) UI de chips seleccionables, (4) aceptar la fricción de convertir one-shot
      en turno de aclaración. **Costo en API + frontend, no en IA.** Merece su
      propio cambio SDD, NO colgado del fix de detección.

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

## Fase 6 — Confiabilidad del instrumental (2026-07-16)

**Por qué existe esta fase.** Todo probe es una AFIRMACIÓN SOBRE PRODUCCIÓN. Cuando
producción cambia, el probe no se rompe: sigue corriendo, sigue imprimiendo
números, y esos números se vuelven mentira en silencio. Pasó dos veces:

- **`retrieval_probe` MINTIÓ** (arreglado, `d4af51a`). Medía `hybrid_search` y lo
  llamaba "el contexto". Produjo el "gap sistémico familia 383" — 5 preguntas —
  cuando 4 de las 5 rutean y contestan bien citando `383.3.d`. Una sola estaba
  rota. Casi arrancamos un SDD para arreglar un problema inexistente.
- **`card_presence_probe` tenía un AGUJERO DE COBERTURA** (arreglado, ver 6.1).
  Distinto pecado: no mentía sobre su número, pero lo medía sobre la población
  equivocada — 15 de 21 preguntas hard rutean y él miraba el contexto que esas 15
  descartan. Un guard que dice "todo OK" sin mirar el path real.

La diferencia importa. Lo primero es un error de método (medir un arm intermedio y
extrapolar). Lo segundo es entropía: la feature se movió abajo del guard y el
guard no se rompió — siguió imprimiendo un 100% verdadero-por-casualidad. Nadie se
equivocó, y por eso nadie lo vio.

### 6.1 ✅ Auditar `card_presence_probe` — HECHO (2026-07-16). Agujero de cobertura cerrado; el guard NO encontró bug

**Corrección primero: la hipótesis con la que se abrió este ítem era equivocada.**
Se escribió que la medición "9/12 cartas ausentes" citada en `pipeline.py:240`
estaba *stale*. **No lo está.** Leída completa, la cita dice: *"a deterministic
probe found 9/12 named cards ABSENT... Detected names join the user-directed tags
so tagged_lookup pulls them into reserved slots"* — el 9/12 es el diagnóstico
**PREVIO al fix**, el que MOTIVÓ construir los auto card tags. Es historia, y la
historia no queda vieja: pasó. El error fue citar de memoria en vez de leer.

**El punto ciego SÍ era real, pero por otro motivo — y peor.** El probe es el
*guard* del fix (su docstring: "a delivery rate below ~100% means the
assembly/budget regressed"). Medido: **15 de las 21 preguntas hard RUTEAN**, y una
query ruteada descarta el contexto recuperado entero (`chunks = stuffed`,
pipeline.py:699). O sea que para el **71% de su propio bucket** el guard medía un
contexto que producción tira, y era **ciego a regresiones en el path que esas 15
realmente usan** (el stuffing). Reportaba un 100% confiado mirando la puerta
equivocada.

**Fix aplicado**: resuelve el camino real por pregunta y difiere al pipeline de
verdad (`build_stuffed_chunks` si rutea, `_retrieve` si no) en vez de re-implementar
la assembly — la copia local es exactamente lo que había derivado. Reutiliza
`routing_decision`/`split_by_route` de `retrieval_probe` (una sola definición de
"¿producción rutea esto?", o los dos probes vuelven a divergir).

**Resultado del gate: el 100% SOBREVIVE. No había bug.**

| Path | Delivery | Preguntas |
|---|---|---|
| routed (stuffed) | **25/25 (100%)** | 15 |
| rag (assembly) | **4/4 (100%)** | 6 |

Lo que cambió no es el número, es su naturaleza: antes era 100% **por casualidad**
(midiendo contexto descartado), ahora es 100% **medido sobre el contexto real**. Y
quedó medido algo que nunca lo había estado: **el stuffing entrega 25/25**. Cita de
`pipeline.py:240` actualizada con la medición nueva y con la aclaración de que el
9/12 es pre-fix.

**Lo que NO se hace (y por qué):** no se toca la feature. Aparte de este probe
tiene evidencia independiente (eval-029 e2e, `correct`/conf=1.0). Y el scan de
~960 patrones **no es opcional aunque el contexto de las ruteadas se descarte**:
`card_count` alimenta `is_hard_query` → **decide el routing mismo**. Sacarlo
rompería la decisión, no solo el contexto. Anotado en el docstring para el que
venga.

### 6.2 ✅ Arm FTS: el 0% es ESPERADO, no un bug — HECHO (2026-07-16)

**Medido:** `plainto_tsquery` **ANDea todos los términos**. Una pregunta natural de
20 palabras exige un chunk que contenga las 20 → matchea nada. Por eso todo probe
reporta `fts 0%` en todos los k. Es la consecuencia esperada de cómo se lo llama.

**El arm FUNCIONA** — se verificó contra la DB real, y esto es lo que importa:

| Query | Resultado |
|---|---|
| `banish` | `427. Banish` |
| `triggered abilities` | `506. Triggered Abilities`, **`383. Triggered Abilities`** |
| pregunta entera de eval-020 | 0 hits |

Confirmado además que en prod el arm está dormido **a propósito**:
`_hybrid_search_impl` fusiona contra una lista FTS **vacía** (nunca llama a
`fts_search`), porque vector-only @5 (47%) medía POR ENCIMA de vector+FTS (41%) —
la pregunta entera diluía el RRF. Rationale ya escrito en `retrieval.py:245-252`.

Gate cumplido (era esperado) → documentado en el docstring de `fts_search`, con la
trampa explícita para el que venga: *antes de concluir que este arm está muerto,
fijate qué le estás dando de comer*. Cerrado.

**⚠️ LEAD INCIDENTAL para 3.11.1 — es un LEAD, NO un resultado.** Mientras se
confirmaba el 0%, salió esto: FTS con `"triggered abilities"` devuelve la sección
`383. Triggered Abilities`, y uno de esos chunks lista **`383.3.d.1`** — que por
lineage padre-hijo **CUBRE el `383.3.d` que le falta a eval-020** (verificado:
`_rule_codes_cover('383.3.d', {'383.3.d.1'}) → True`). El sub-rule catalogado como
"ni en vector top-50" es recuperable con una query de DOS palabras.

Por qué esto NO contradice a 3.6 ni resucita nada por decreto:
- 3.6 murió sobre **eval-014/019** con sus términos, no sobre eval-020.
- Lo de ayer mató `"trigger"` como **keyword para `_complete_keyword_families`** —
  mecanismo distinto: esa compuerta exige un chunk de la familia sobreviviente al
  retrieval. **Un arm FTS no necesita compuerta.**
- Falta lo esencial y no está medido: que la extracción determinística produzca
  el término desde la pregunta de eval-020 ("...when Temporary **triggers**?").
  Ese es justo el modo en que murió 3.6 (los términos ganadores no estaban en la
  pregunta). **Acá sí está la palabra** — pero eso hay que MEDIRLO, no asumirlo.

Se ataca en 3.11.1 con su gate, no acá. Anotado porque el hallazgo es real y se
pierde si no se escribe.

### 6.3 ✅ Deuda del review del probe — HECHA (2026-07-16)

- [x] **`_NoHydeProvider` frágil → ARREGLADO.** Era una clase pelada con solo
      `hyde()`. Los probes no se pueden testear end-to-end (necesitan DB), así que
      un método nuevo en el provider habría aparecido como `AttributeError` en una
      corrida manual, con CI en verde — justo cuando estás debuggeando otra cosa y
      confiando en la herramienta sin mirarla. Ahora **subclasea el ABC real**
      (`LLMProvider`), lo que mueve la falla a tiempo de construcción, y 4 tests
      la convierten en falla de CI: agregás un `@abstractmethod` a `LLMProvider` y
      `test_stub_can_be_constructed` rompe al instante. `generate()` levanta
      `NotImplementedError` con el motivo escrito, no un `AttributeError` mudo que
      mande al próximo a cazar el bug equivocado.
- [x] **`hybrid_search` "duplicado" → WON'T FIX, y el review se apuró (era mío).**
      Los parámetros NO coinciden: `_retrieve` fetchea a `top_k_fetch=15` y shippea
      `top_k=5`; el diagnóstico va a **15/30 a propósito**, y esa profundidad extra
      es justo lo que le permite separar "el gold está en rank 12" (problema de
      ranking) de "el gold no está en ningún lado" (problema de chunking) — el
      split para el que el diagnóstico existe. Deduplicarlo exigiría achicar el
      diagnóstico o hacer que `_retrieve` exponga sus internals para servir a un
      probe. Una query extra en una herramienta manual es el trade barato.
      Motivo escrito en el código para que el próximo review no lo re-levante.

### 6.4 Regla de la casa (nueva, sale de esta fase)

Un probe que no modela el camino real de producción no es un probe: es una
opinión con formato de tabla. **Antes de creerle un número a cualquier probe,
verificar que su modelo del pipeline siga siendo el pipeline.** El costo de no
hacerlo ya está medido: un día de diagnóstico sobre un gap inexistente.

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
- [x] Log `query.complete` engañoso: YA ARREGLADO por el routing (#58/#59) —
      `model = settings.hard_gemini_model if routed else (settings.llm_model or
      settings.gemini_model)`. Este ítem estaba desactualizado.
- [x] `_hyde_gemini`/`_hyde_openai_compat` tragan excepciones sin loguear —
      HECHO 2026-07-13: `logger.warning` en ambas, never-raise contract intacto.
- [x] Commitear este archivo (entró con la PR de la maquinaria 3.8).
