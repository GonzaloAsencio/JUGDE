# 06 - Retrieval Ablation Specification

> **Nota histórica (superseded):** los snippets de esta spec usan retrievers de
> LlamaIndex (BM25Retriever, QueryFusionRetriever, FlagEmbeddingReranker). La
> implementación final hace hybrid retrieval con SQL directo sobre `pgvector` +
> FTS de Postgres y un Reciprocal Rank Fusion propio (`app/rag/retrieval.py`,
> `_rrf_fuse`). El estudio de ablation y su razonamiento siguen vigentes; solo
> cambió cómo está construido el retriever. Ver ADR-001.

## Por qué esta spec es el corazón de tu portfolio

El ablation study es **lo que vas a contar en el blog post**. Es la diferencia entre "seguí un tutorial de RAG" y "entiendo RAG en profundidad".

Sin ablation, tu repo es uno más. Con ablation y números reales, sos contratable.

## Objetivo

Comparar al menos 4 configuraciones de retrieval contra el mismo eval set, generar una tabla con números, y tomar decisiones basadas en datos.

## Configuraciones a comparar

### Config A: Baseline (de spec 05)
- Dense retrieval (vector similarity)
- Top-K = 5
- bge-m3 embeddings
- Sin reranker

### Config B: Hybrid retrieval
- Dense + BM25 (via Postgres tsvector)
- Reciprocal Rank Fusion para combinar
- Top-K = 5 final (después de fusion)
- Sin reranker

### Config C: Hybrid + Reranker
- Hybrid retrieval (igual que B)
- Top-K = 20 inicial → reranker → Top-N = 5 final
- Cross-encoder: `BAAI/bge-reranker-large`

### Config D: Hybrid + Reranker + Entity Resolution
- Solo si decisión de spec 07 es SÍ
- Hybrid + reranker + inyección de texto de cartas mencionadas

### (Opcional) Variaciones de chunking
Si tiempo permite, probar mismos configs con:
- Chunk size 256
- Chunk size 512 (default)
- Chunk size 1024

## Métricas a medir

Para cada config:

| Métrica | Cómo medir |
|---|---|
| Faithfulness | RAGAS |
| Answer relevancy | RAGAS |
| Context precision | RAGAS |
| Context recall | RAGAS |
| Latency p50 | Timing en código |
| Latency p95 | Timing en código |
| Cost per query | Tokens × precio Gemini |
| Failure rate by category | Análisis manual sobre eval set categorizado |

## Análisis de fallos por categoría (crítico)

Esto es lo que decide si necesitás entity resolution.

```python
# scripts/analyze_failures.py

def categorize_failures(eval_results, eval_set):
    failures = {
        "card_specific_failed": 0,
        "card_specific_total": 0,
        "keyword_specific_failed": 0,
        "keyword_specific_total": 0,
        "multi_step_failed": 0,
        "multi_step_total": 0,
        # ...
    }
    
    for result, question in zip(eval_results, eval_set):
        if question["category"]["mentions_specific_cards"]:
            failures["card_specific_total"] += 1
            if result["faithfulness"] < 0.7:
                failures["card_specific_failed"] += 1
        # ... más categorías
    
    return failures
```

**Decisión clave de semana 3:**

Si `card_specific_failed / card_specific_total > 0.20` (20% de fallo en preguntas con cartas):
→ **Implementar entity resolution (spec 07)**

Si menor a 20%:
→ **Skip entity resolution, anotar en FUTURE_WORK.md**

## Implementación de Hybrid Retrieval

```python
# app/rag/retrieval.py

from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.core.retrievers import QueryFusionRetriever

def build_hybrid_retriever(index):
    vector_retriever = index.as_retriever(similarity_top_k=20)
    
    bm25_retriever = BM25Retriever.from_defaults(
        nodes=index.docstore.docs.values(),
        similarity_top_k=20,
    )
    
    fusion_retriever = QueryFusionRetriever(
        retrievers=[vector_retriever, bm25_retriever],
        similarity_top_k=10,
        mode="reciprocal_rerank",  # RRF
        use_async=True,
    )
    
    return fusion_retriever
```

## Implementación de Reranker

```python
from llama_index.postprocessor.flag_embedding_reranker import FlagEmbeddingReranker

reranker = FlagEmbeddingReranker(
    model="BAAI/bge-reranker-large",
    top_n=5,
)

query_engine = index.as_query_engine(
    retriever=fusion_retriever,
    node_postprocessors=[reranker],
)
```

## Output esperado

### Tabla de resultados (va al README)

| Config | Faith. | Ans.Rel. | Ctx.Prec. | Ctx.Rec. | p50 | p95 | $/query |
|---|---|---|---|---|---|---|---|
| A: Vector only | 0.72 | 0.78 | 0.61 | 0.68 | 1.8s | 3.2s | $0.0003 |
| B: Hybrid | 0.78 | 0.81 | 0.72 | 0.75 | 2.1s | 3.8s | $0.0003 |
| C: Hybrid + RR | 0.84 | 0.83 | 0.81 | 0.79 | 2.8s | 4.5s | $0.0003 |
| D: + Entity Res | 0.89 | 0.86 | 0.83 | 0.81 | 3.0s | 4.8s | $0.0004 |

(Los números son ilustrativos, los reales saldrán de tus runs.)

### Análisis cualitativo (va al blog post)

Por cada config, anotar:

- ¿Qué tipo de preguntas mejoró?
- ¿Qué tipo se mantuvo igual?
- ¿Qué tipo empeoró? (sí, puede empeorar)
- Sorpresas: cosas que esperabas que mejoraran y no, o viceversa

**Ejemplo de insight para blog post:**

> "Esperaba que el reranker mejorara dramáticamente en multi-step questions. 
> En realidad, las mejoras fueron principalmente en factual queries con 
> términos ambiguos. El reranker desambigua, no razona. Esto cambia cómo 
> pensaría su uso en sistemas más complejos."

## Estructura de archivos generada

```
backend/data/eval_runs/
├── 2026-05-20_config_a_baseline.json
├── 2026-05-21_config_b_hybrid.json
├── 2026-05-22_config_c_reranker.json
├── 2026-05-23_config_d_entity_resolution.json
├── failure_analysis_2026-05-23.json
└── comparison_table.md
```

## Criterio de "ablation terminado"

- [ ] Al menos 3 configs corridas (4 si entity resolution = sí)
- [ ] Cada config tiene su archivo JSON de resultados
- [ ] Tabla comparativa generada en Markdown
- [ ] Análisis de fallos por categoría hecho
- [ ] Decisión sobre entity resolution tomada con justificación
- [ ] Config ganadora elegida y deployed como default

## Anti-patterns a evitar

❌ Comparar configs con datasets distintos
❌ Cambiar el prompt entre configs (no es ablation limpio)
❌ Optimizar el prompt para una config específica
❌ Reportar solo accuracy, omitir latencia y costo
❌ Decidir basándose en intuición vs datos

✅ Mismo eval set, mismo prompt, solo cambia retrieval
✅ Múltiples runs por config (3 mínimo) para variance
✅ Reportar todas las métricas, no solo las que favorecen
✅ Documentar lo que NO funcionó (también es valioso)
