# 01 - Tech Stack (Final, No More Debates)

## Backend

| Componente | Elección | Razón |
|---|---|---|
| Lenguaje | Python 3.12 | Ecosistema RAG maduro |
| Framework web | FastAPI | Async nativo, Pydantic, estándar industria |
| RAG orchestration | psycopg2 + pgvector directo (RRF propio) | Evalué LlamaIndex pero lo descarté — ver nota abajo |
| Embeddings | BAAI/bge-m3 | Multilingüe, futureproof, gratis local |
| Vector store | pgvector en Supabase | Mismo DB que app data |
| LLM | Gemini 2.5 Flash | Free tier generoso (1M tok/día) |
| Cache | Upstash Redis | Free tier 10k commands/día |
| Rate limiting | slowapi | Simple, basado en starlette |
| Hosting | Render free → Standard $7 | Sin cold starts en paid |

## Frontend

| Componente | Elección | Razón |
|---|---|---|
| Framework | Next.js 16 | App Router, estándar moderno |
| Lenguaje | TypeScript | Type safety |
| Styling | Tailwind CSS + shadcn/ui | Rápido, buen default visual |
| State | Zustand o Context | Simple, suficiente para scope |
| LLM streaming | Vercel AI SDK | Streaming integrado |
| Markdown render | react-markdown + rehype | Para tab Rules |
| Hosting | Vercel free → Pro $20 | Si se necesita |

## Observabilidad

| Componente | Elección | Razón |
|---|---|---|
| Tracing | Langfuse Cloud | Free 50k observations/mes, no self-host |
| Errores | Sentry free | 5k errors/mes |
| Logs | print + Render logs | Suficiente para portfolio |

## Evaluación

> **Status (histórico):** RAGAS fue el plan; la implementación final usa
> LLM-as-judge — ver **ADR-006** y el README.

| Componente | Elección (real) | Razón |
|---|---|---|
| Framework | LLM-as-judge (Gemini) | Sin dependencia extra, reusa el `LLMProvider` (ver ADR-006) |
| Métricas | verdict `correct`/`partial`/`wrong` + retrieval recall determinístico | Suficiente para un baseline medido rápido |

## Data sources

| Qué | Fuente | Status |
|---|---|---|
| Reglamento | PDF oficial de Riftbound | Manual download |
| FAQ / Errata | Web oficial | Copy-paste a Markdown |
| Cartas | Riftcodex API (community) | Fallback: JSON manual |
| API oficial Riot | Pendiente aprobación | NO bloqueante |

## Lo que NO usamos (y por qué)

| NO usado | Por qué |
|---|---|
| LlamaIndex | Lo evalué para orquestar el RAG. La query engine resuelve embed→retrieve→synthesize en pocas líneas, pero abstrae justo lo que yo quería controlar a mano: el hybrid retrieval (vector + FTS con Reciprocal Rank Fusion propio), la cadena de autoridad por `source_type` (errata > patch_notes > rulebook) y el prompt de generación. Implementar eso sobre LlamaIndex significaba pelearme con sus retrievers y postprocessors; hacerlo con `psycopg2` + `pgvector` directo son ~200 líneas de SQL y Python que entiendo de punta a punta, sin una dependencia pesada que esconda el ranking. Para un proyecto cuyo diferencial ES el retrieval, el control vale más que el atajo. |
| LangChain | Misma razón que LlamaIndex (capa de orquestación que no necesito), con aún más abstracción |
| OpenAI embeddings | Pago, no necesario |
| Pinecone / Qdrant cloud | pgvector alcanza |
| Tiptap editor | Overkill, `<input>` + datalist alcanza |
| PWA / Service worker | Out of scope |
| Microservices | Premature optimization |
| Docker compose multi-service | Un servicio backend, no hace falta |

## Costos esperados

| Etapa | Cash/mes |
|---|---|
| Desarrollo (semanas 1-6) | $0 |
| Post-launch, <500 usuarios | $0 |
| 500-5000 usuarios | $25-50 |
| 5000+ usuarios | Decidir entonces |

## Variables de entorno necesarias

```
# Backend (.env)
GEMINI_API_KEY=
SUPABASE_URL=
SUPABASE_KEY=
DATABASE_URL=
UPSTASH_REDIS_URL=
UPSTASH_REDIS_TOKEN=
SENTRY_DSN=
LANGFUSE_PUBLIC_KEY=
LANGFUSE_SECRET_KEY=

# Frontend (.env.local)
NEXT_PUBLIC_API_URL=
```
