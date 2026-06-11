# 04 - Corpus Specification

## Objetivo

Tener un corpus limpio, estructurado y versionado del reglamento de Riftbound, listo para chunking y embedding.

## Fuentes de datos

### Reglamento principal
- **Fuente:** PDF oficial de Riftbound (descarga manual desde web oficial)
- **Formato origen:** PDF
- **Formato destino:** Markdown estructurado con secciones jerárquicas

### FAQ oficial
- **Fuente:** Página web oficial Riftbound
- **Formato origen:** HTML
- **Formato destino:** Markdown, una entrada por sección

### Errata
- **Fuente:** Página web oficial Riftbound
- **Formato origen:** HTML
- **Formato destino:** Markdown con fecha de cada errata

### Cartas (separado, ver más abajo)
- **Fuente primaria:** Riftcodex (API comunitaria) o riftbound.gg
- **Fuente fallback:** JSON manual con ~100 cartas críticas
- **Formato destino:** JSON estructurado para tabla `cards`

## Estructura de archivos

```
backend/
├── data/
│   ├── raw/
│   │   ├── rulebook.pdf
│   │   ├── faq_2026-05-13.html
│   │   └── errata_2026-05-13.html
│   ├── processed/
│   │   ├── rulebook.md
│   │   ├── faq.md
│   │   └── errata.md
│   ├── cards/
│   │   ├── cards.json
│   │   └── keywords_dictionary.json  # opcional, decisión semana 3
│   └── eval_set.json
└── scripts/
    ├── parse_rulebook.py
    ├── parse_faq.py
    └── ingest.py
```

## Proceso de parseo

### Reglamento (PDF → Markdown)

```python
# scripts/parse_rulebook.py
# Usa pymupdf (fitz) para extraer texto manteniendo estructura
# Detecta headers por tamaño de fuente
# Preserva listas numeradas
# Output: rulebook.md con jerarquía # / ## / ### / ####
```

**Validación manual obligatoria:**
- Comparar primeras 5 páginas PDF vs Markdown
- Verificar que no se perdieron secciones
- Verificar que números de regla (1.1, 1.2, etc.) están preservados

### FAQ / Errata (HTML → Markdown)

```python
# scripts/parse_faq.py
# BeautifulSoup para extraer secciones
# Una sección por pregunta de FAQ
# Metadata: fecha, set relacionado, categoría
```

## Schema de chunks en BD

```sql
CREATE TABLE corpus_chunks (
  id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
  content TEXT NOT NULL,
  embedding VECTOR(1024),  -- bge-m3 dimension
  source_type TEXT NOT NULL,  -- 'rulebook' | 'faq' | 'errata' | 'card_text'
  source_document TEXT NOT NULL,
  section TEXT,
  parent_section TEXT,
  metadata JSONB,
  corpus_version TEXT NOT NULL,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX corpus_chunks_embedding_idx ON corpus_chunks 
  USING ivfflat (embedding vector_cosine_ops);

CREATE INDEX corpus_chunks_content_fts_idx ON corpus_chunks 
  USING gin(to_tsvector('english', content));
```

## Estrategia de chunking

**Default:** Structural-aware chunking respetando secciones del reglamento.

**Parámetros iniciales:**
- Chunk size: 512 tokens
- Overlap: 50 tokens
- Respetar boundaries de secciones (no partir reglas a la mitad)

**Iteración semana 3:** probar otros sizes (256, 1024) en el ablation.

## Tabla de cartas

```sql
CREATE TABLE cards (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  alternate_names TEXT[],
  set_code TEXT,
  type TEXT,
  faction TEXT,
  cost INTEGER,
  text TEXT,
  keywords TEXT[],
  metadata JSONB,
  embedding VECTOR(1024),
  is_active BOOLEAN DEFAULT TRUE,
  created_at TIMESTAMP DEFAULT NOW()
);

CREATE INDEX cards_name_trgm_idx ON cards 
  USING gin(name gin_trgm_ops);
```

**Nota sobre versionado de cartas:**

El blueprint v1 tenía una tabla `card_versions` para historial completo. **Eso queda fuera de scope v2.** Si una carta recibe errata, simplemente actualizás el texto. El historial queda en `corpus_chunks` con su `corpus_version` original.

## Versionado del corpus

Cada vez que se hace ingest, se asigna un `corpus_version`:

- `v1.0.0`: ingest inicial
- `v1.0.1`: parche menor (corrección de parsing)
- `v1.1.0`: nueva FAQ agregada
- `v2.0.0`: nuevo set

Cada query loggea el `corpus_version` activo al momento de responder.

## Script de ingest

```python
# scripts/ingest.py
# Pipeline:
# 1. Read rulebook.md
# 2. Chunk with structural awareness
# 3. Generate embeddings with bge-m3
# 4. Upsert to pgvector
# 5. Tag with corpus_version
# 6. Log summary

# Modes:
# --dry-run: muestra qué haría, no escribe
# --fresh: drop chunks, re-insertar todo
# --update: solo insertar nuevos
```

## Criterio de "corpus listo"

- [ ] `rulebook.md` revisable y completo
- [ ] `faq.md` y `errata.md` presentes
- [ ] `cards.json` con al menos 100 cartas
- [ ] Script `ingest.py` funciona end-to-end
- [ ] `corpus_chunks` poblada en Supabase
- [ ] Query de prueba en pgvector retorna resultados sensatos

## Anti-patterns a evitar

❌ Parsear el PDF a texto plano sin estructura (pierde jerarquía)
❌ Hacer chunks de tamaño fijo ignorando secciones
❌ Embeddear el reglamento completo como un solo documento
❌ Olvidar el versionado desde el principio
❌ Cargar cartas sin validar duplicados o nombres

✅ Markdown con headers preservados
✅ Chunks respetan boundaries semánticos
✅ Metadata rica para filtrar después
✅ Versionado desde el ingest inicial
✅ Validación manual de los primeros 20 chunks
