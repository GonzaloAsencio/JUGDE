# 05 - RAG Pipeline Baseline

> **Nota histórica (superseded):** los ejemplos de código de esta spec usan
> LlamaIndex, que fue el plan inicial. La implementación final NO usa LlamaIndex:
> orquesta el pipeline directo con `psycopg2` + `pgvector` y un RRF propio (ver
> ADR-001 en `10_portfolio_polish.md` y la tabla "Lo que NO usamos" en
> `01_tech_stack.md`). El diseño conceptual de abajo sigue siendo válido; solo
> cambió la herramienta.
>
> Además, la evaluación final **no usa RAGAS** (los snippets `from ragas import
> evaluate` de abajo son del plan original): se implementó un harness
> LLM-as-judge — ver **ADR-006** y el README. El racional del eval sigue válido;
> cambió el framework de medición.

## Objetivo

Pipeline RAG funcional **simple** que se pueda medir contra el eval set. Es el punto de comparación para todas las mejoras posteriores.

**Regla:** sin trucos. Solo lo mínimo para que funcione end-to-end.

## Lo que SÍ incluye el baseline

- Chunking estructural (definido en spec 04)
- Embeddings con bge-m3
- Retrieval vectorial puro (sin BM25, sin hybrid)
- Top-K = 5 chunks
- Sin reranker
- Sin entity resolution
- Sin clasificador de query
- Gemini Flash con prompt simple
- Output con citas

## Lo que NO incluye el baseline

- ❌ Hybrid retrieval (BM25 + vector)
- ❌ Reciprocal Rank Fusion
- ❌ Cross-encoder reranker
- ❌ Query classification
- ❌ @mention entity resolution
- ❌ Cache (viene semana 5)
- ❌ Rate limiting (viene semana 5)

Todo esto viene en semanas 3 y 5, **después** de medir el baseline.

## Arquitectura

```
[Query del usuario]
       ↓
[FastAPI endpoint /api/v1/query]
       ↓
[LlamaIndex VectorStoreIndex.as_query_engine()]
       ↓
[bge-m3 embedding de la query]
       ↓
[pgvector similarity search, top_k=5]
       ↓
[Construir prompt con system + chunks + query]
       ↓
[Gemini Flash via google-generativeai]
       ↓
[Parsear respuesta a schema Pydantic]
       ↓
[Devolver JSON con respuesta + citas]
```

## Schema de request/response

### Request

```python
class QueryRequest(BaseModel):
    question: str
    language: Literal["en", "es"] = "en"
    session_id: Optional[str] = None
```

### Response

```python
class Citation(BaseModel):
    source_document: str
    section: str
    chunk_id: str
    relevance_score: float

class QueryResponse(BaseModel):
    answer: str
    citations: List[Citation]
    confidence: Literal["high", "medium", "low"]
    defer_to_judge: bool
    query_id: str
    corpus_version: str
    latency_ms: int
```

## System prompt baseline

```
You are a Riftbound TCG rules assistant. Your job is to answer rules 
questions accurately based ONLY on the provided context.

RULES:
1. Answer only from the provided context. If the context doesn't contain 
   the answer, say "I don't have enough information to answer this. 
   Please consult a tournament judge."
2. Always cite your sources by referencing the section number.
3. Be concise. Players need answers in seconds.
4. If multiple rules apply, mention all of them.
5. If there's ambiguity, flag it explicitly.

OUTPUT FORMAT (JSON):
{
  "answer": "...",
  "citations": [{"section": "...", "quote": "..."}],
  "confidence": "high|medium|low",
  "defer_to_judge": true|false
}
```

## Estructura de código

```
backend/
├── app/
│   ├── main.py                 # FastAPI app
│   ├── api/
│   │   └── v1/
│   │       └── query.py        # Endpoint /query
│   ├── rag/
│   │   ├── pipeline.py         # Pipeline RAG principal
│   │   ├── retrieval.py        # Solo vector search (baseline)
│   │   ├── generation.py       # LLM call + prompt
│   │   └── schemas.py          # Pydantic models
│   ├── config.py               # Settings
│   └── db.py                   # Supabase client
├── scripts/
│   └── ingest.py
└── tests/
    └── test_pipeline.py
```

## Implementación con LlamaIndex

```python
# app/rag/pipeline.py

from llama_index.core import VectorStoreIndex, StorageContext
from llama_index.vector_stores.supabase import SupabaseVectorStore
from llama_index.embeddings.huggingface import HuggingFaceEmbedding
from llama_index.llms.gemini import Gemini
from llama_index.core import Settings

def build_pipeline():
    Settings.embed_model = HuggingFaceEmbedding(model_name="BAAI/bge-m3")
    Settings.llm = Gemini(model="models/gemini-2.5-flash")
    
    vector_store = SupabaseVectorStore(
        postgres_connection_string=settings.DATABASE_URL,
        collection_name="corpus_chunks",
    )
    
    storage_context = StorageContext.from_defaults(vector_store=vector_store)
    index = VectorStoreIndex.from_vector_store(vector_store)
    
    query_engine = index.as_query_engine(
        similarity_top_k=5,
        response_mode="compact",
    )
    
    return query_engine

async def query(question: str) -> QueryResponse:
    query_engine = build_pipeline()
    response = query_engine.query(question)
    
    return QueryResponse(
        answer=str(response),
        citations=extract_citations(response.source_nodes),
        # ... etc
    )
```

## Eval del baseline

Una vez que el endpoint funcione, correr eval:

```python
# scripts/run_eval.py

from ragas import evaluate
from ragas.metrics import (
    faithfulness,
    answer_relevancy,
    context_precision,
    context_recall,
)

eval_set = load_eval_set("data/eval_set.json")

results = []
for question in eval_set:
    response = pipeline.query(question["question"])
    results.append({
        "question": question["question"],
        "answer": response.answer,
        "ground_truth": question["canonical_answer"],
        "contexts": [c.content for c in response.source_nodes],
    })

scores = evaluate(
    results,
    metrics=[faithfulness, answer_relevancy, context_precision, context_recall],
)

# Guardar en data/eval_runs/{date}_baseline.json
```

## Criterio de "baseline listo"

- [ ] Endpoint `/api/v1/query` responde
- [ ] Devuelve respuesta + citas + confidence
- [ ] Eval corre completo sobre las 50 preguntas
- [ ] Métricas RAGAS calculadas y guardadas
- [ ] Latencia p50 < 3000ms (sin optimizar)
- [ ] Tests básicos pasan

## Métricas baseline esperadas (proyección)

Estos son números **esperados**, no targets:

| Métrica | Esperado |
|---|---|
| Faithfulness | 0.65-0.80 |
| Answer relevancy | 0.70-0.85 |
| Context precision | 0.50-0.70 |
| Context recall | 0.60-0.75 |
| Latency p50 | 1500-3000ms |
| Latency p95 | 3000-5000ms |

Si los números están muy por debajo, hay bug. Si están muy por encima, sospechá del eval set.

## Anti-patterns a evitar

❌ Saltarse el baseline e ir directo a hybrid + reranker
❌ Optimizar el system prompt antes de tener números baseline
❌ Hacer multiple llamadas a LLM (clasificador + answer) en el baseline
❌ Agregar caching antes de tener números limpios

✅ Pipeline más simple posible que funcione
✅ Medir antes de optimizar
✅ Documentar las decisiones (chunk size, top_k, etc.)
✅ Reproducible: anyone puede correr el mismo eval
