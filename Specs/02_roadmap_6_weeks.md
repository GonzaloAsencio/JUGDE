# 02 - Roadmap 6 semanas

> **Status (histórico):** Plan de 6 semanas original. El orden real fue distinto
> (el eval se construyó al final, no en la Semana 1) y la evaluación usa
> LLM-as-judge, no RAGAS — ver **ADR-006** y el README. Se conserva como registro
> del plan inicial.

## Semana 1: Foundation (Eval set + Corpus)

**Objetivo:** Tener datos para experimentar. **Esta es la semana más importante.**

**Entregables:**
- [ ] Repo GitHub creado con estructura `/backend` y `/frontend`
- [ ] Reglamento PDF parseado a Markdown limpio
- [ ] FAQ y errata recolectados a Markdown
- [ ] 40-60 preguntas de eval con respuestas canónicas + citas
- [ ] Eval set clasificado por dificultad
- [ ] Supabase project creado

**Criterio de éxito:**
- Eval set revisable por un jugador experimentado
- Todas las preguntas son respondibles desde el corpus

**Ver:** `03_eval_set_spec.md`, `04_corpus_spec.md`

---

## Semana 2: Baseline RAG

**Objetivo:** Pipeline RAG funcional simple. Sin trucos.

**Entregables:**
- [ ] FastAPI skeleton deployed en Render
- [ ] Pipeline RAG con chunking default _(plan inicial decía LlamaIndex; la implementación final usa pgvector directo + RRF propio — ver ADR-001)_
- [ ] Embeddings bge-m3 en pgvector
- [ ] Endpoint `/api/v1/query` funcional
- [ ] Integración Gemini Flash
- [ ] Primer run de eval con métricas RAGAS
- [ ] Baseline numbers documentados

**Criterio de éxito:**
- Query end-to-end retorna respuesta con citas
- Eval corre de forma reproducible
- Números baseline anotados (faithfulness, accuracy)

**Ver:** `05_rag_pipeline_baseline.md`

---

## Semana 3: Retrieval Ablation + Entity Resolution (decisión)

**Objetivo:** Comparar configuraciones, decidir entity resolution basado en datos.

**Entregables:**
- [ ] Hybrid retrieval (dense + BM25) implementado
- [ ] Reciprocal Rank Fusion implementado
- [ ] Cross-encoder reranker probado
- [ ] Eval corrido por cada configuración
- [ ] Tabla comparativa de resultados
- [ ] **Análisis de fallos por categoría** (cuántas preguntas con cartas específicas fallan?)
- [ ] **DECISIÓN:** ¿implementar entity resolution con @mentions?
- [ ] Si decisión = SÍ: spec ejecutada según `07_entity_resolution_spec.md`

**Criterio de éxito:**
- Al menos 3 configuraciones comparadas con números
- Decisión sobre entity resolution justificada con datos del eval
- Configuración ganadora documentada con rationale

**Ver:** `06_retrieval_ablation_spec.md`, `07_entity_resolution_spec.md`

---

## Semana 4: Frontend MVP + Tab Rules

**Objetivo:** UI mínima funcional + browse del reglamento.

**Entregables:**
- [ ] Next.js app deployed en Vercel
- [ ] Pantalla principal: input + respuesta + citas + feedback
- [ ] Streaming de respuesta funcionando
- [ ] Citas clickeables (linkean al tab Rules con scroll a sección)
- [ ] Tab Rules: render del reglamento con TOC auto-generado
- [ ] Mobile responsive básico
- [ ] 3 example queries pre-cargadas como botones

**Criterio de éxito:**
- URL shareable que funciona en desktop y mobile
- Recruiter puede entender qué hace en 5 segundos
- Tab Rules muestra corpus completo para transparencia

**Ver:** `08_frontend_spec.md`

---

## Semana 5: Production Hardening

**Objetivo:** Que el demo no se rompa cuando lo compartas.

**Entregables:**
- [ ] Redis cache para queries (TTL 24h)
- [ ] Rate limiting (10 req/min por IP)
- [ ] Sentry integrado backend
- [ ] Langfuse traces visibles
- [ ] Input validation con Pydantic
- [ ] Prompt injection defense básica (system prompt)
- [ ] Error handling graceful en UI
- [ ] Logs estructurados

**Criterio de éxito:**
- Cache hit rate visible en logs
- Rate limiter testeado
- App no crashea con input raro

**Ver:** `09_production_hardening.md`

---

## Semana 6: Portfolio Polish + Launch

**Objetivo:** Convertir el proyecto en activo de portfolio.

**Entregables:**
- [ ] README con architecture diagram (Mermaid o imagen)
- [ ] README con tabla de resultados
- [ ] README con decision log / ADRs
- [ ] Setup instructions reproducibles
- [ ] Blog post de 1500-2500 palabras publicado
- [ ] Video demo de 3 minutos
- [ ] 5 demo queries preparadas para entrevistas
- [ ] LinkedIn post anunciando

**Criterio de éxito:**
- Link compartible con orgullo a un recruiter
- Historia clara en 30 segundos
- Cada claim del README respaldado por números

**Ver:** `10_portfolio_polish.md`

---

## Reglas de ejecución

1. **No saltarse la semana 1.** El eval set determina todo lo demás.
2. **Decisiones de semana 3 basadas en datos, no en gustos.**
3. **Si algo no está en estas specs, no se hace.** Va a `FUTURE_WORK.md`.
4. **Time-box estricto.** Si una semana se va de 7 días, recortar scope, no extender plazo.
5. **Commit diario.** Aunque sea WIP.

## Métricas de progreso

Semanalmente revisar:
- ¿Entregables completos?
- ¿Criterio de éxito cumplido?
- ¿Algo se desvió del scope?

Si la respuesta a la última es sí: **stop, revisar, decidir si volver a scope o ajustar formalmente.**
