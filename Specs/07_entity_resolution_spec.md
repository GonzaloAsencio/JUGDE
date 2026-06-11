# 07 - Entity Resolution Specification

## ⚠️ Esta spec es CONDICIONAL

**Solo se ejecuta si el análisis de fallos en semana 3 muestra que >20% de las preguntas con cartas específicas fallan.**

Si <20% fallan, esta spec se documenta en `FUTURE_WORK.md` y no se implementa.

## Qué es entity resolution en este contexto

Cuando el usuario pregunta sobre cartas específicas (ej: "¿Puede Ahri bloquear?"), el sistema:

1. Detecta que "Ahri" es nombre de carta
2. Busca el texto exacto de Ahri en la tabla `cards`
3. Inyecta ese texto en el contexto del LLM
4. El LLM responde con conocimiento exacto de la carta

Sin entity resolution, el LLM depende de que el embedding semántico encuentre chunks relevantes que mencionen Ahri, lo cual puede fallar si:
- Ahri solo aparece en su carta, no en el reglamento
- El nombre se confunde con otras cartas
- El texto tiene keywords raros no presentes en el reglamento general

## Dos modos de detección

### Modo A: Explícito (`@mentions`) — RECOMENDADO

El usuario marca las cartas con `@`:

```
"Can I block with @Ahri if @Garen was played this turn?"
```

**Pros:**
- Simple de implementar
- Sin falsos positivos
- UX clara (autocomplete sugiere cartas al escribir `@`)

**Cons:**
- Requiere educación del usuario (UI hints)
- Si no usan `@`, no funciona

### Modo B: Auto-detección

El sistema escanea la query y detecta nombres de cartas automáticamente:

```python
def detect_cards(query: str, cards_index: List[str]) -> List[str]:
    # Fuzzy match contra nombres de cartas
    # Plus: alternate names, abreviaciones
```

**Pros:**
- UX más natural (usuario no piensa)
- Funciona aunque no usen `@`

**Cons:**
- Falsos positivos ("the fox" no es Ahri pero se parece)
- "Block" puede ser carta o verbo
- Más complejo de tunear

**Decisión recomendada:** Modo A para v2. Modo B va a `FUTURE_WORK.md`.

## Implementación Modo A (`@mentions`)

### Frontend

**UI behavior:**
1. Usuario escribe `@`
2. Aparece dropdown con cartas que coinciden
3. Usuario selecciona o sigue escribiendo
4. Carta seleccionada queda marcada visualmente como tag
5. Backend recibe array de card_ids junto con query

**Componente (sin Tiptap):**

```tsx
// frontend/components/QueryInput.tsx

function QueryInput() {
  const [text, setText] = useState("");
  const [mentions, setMentions] = useState<Card[]>([]);
  const [showSuggestions, setShowSuggestions] = useState(false);
  
  // Detectar cuando el usuario escribe @
  // Mostrar dropdown con cartas
  // Al seleccionar, reemplazar @text con marker visual
  
  return (
    <div>
      <input 
        value={text}
        onChange={handleChange}
        onKeyDown={handleKeyDown}
      />
      {showSuggestions && <CardSuggestions onSelect={addMention} />}
      <SubmitButton onClick={() => submit(text, mentions)} />
    </div>
  );
}
```

**Endpoint para autocomplete:**

```python
@router.get("/api/v1/cards/search")
async def search_cards(q: str, limit: int = 10):
    # Fuzzy match con pg_trgm
    # Returns: [{"id": "...", "name": "Ahri", "set": "Origins"}, ...]
```

### Backend

**Schema actualizado:**

```python
class QueryRequest(BaseModel):
    question: str
    card_mentions: List[str] = []  # card_ids
    language: Literal["en", "es"] = "en"
    session_id: Optional[str] = None
```

**Pipeline actualizado:**

```python
async def query_with_entity_resolution(request: QueryRequest):
    # 1. Get card texts for mentioned cards
    card_contexts = []
    if request.card_mentions:
        cards = await get_cards(request.card_mentions)
        card_contexts = [
            f"CARD: {c.name} ({c.set_code})\nTEXT: {c.text}\nKEYWORDS: {', '.join(c.keywords)}"
            for c in cards
        ]
    
    # 2. Standard retrieval
    retrieved_chunks = await retriever.retrieve(request.question)
    
    # 3. Build augmented prompt
    prompt = build_prompt(
        question=request.question,
        retrieved_context=retrieved_chunks,
        card_context=card_contexts,  # ← nueva inyección
    )
    
    # 4. LLM call as usual
    response = await llm.generate(prompt)
    
    return response
```

**System prompt actualizado:**

```
You are a Riftbound TCG rules assistant.

CONTEXT SOURCES (in order of priority):
1. SPECIFIC CARD TEXTS (if provided) — authoritative for those cards
2. RULEBOOK SECTIONS — authoritative for general rules
3. FAQ AND ERRATA — authoritative for clarifications

When card-specific text is provided, use it as the source of truth for those 
cards. Don't infer card abilities from general rules if specific text is available.

[resto del prompt baseline]
```

## Diccionario de keywords (decisión separada)

Similar a entity resolution pero para keywords ("Hunt", "XP", "Overnumbered").

**Si en el análisis de fallos también aparecen muchos fallos en preguntas con keywords:**

```python
# data/cards/keywords_dictionary.json
{
  "Hunt": "When a Hunt unit conquers or holds a battlefield, you gain XP equal to the value on the card.",
  "XP": "Experience points that can be spent on level abilities...",
  "Overnumbered": "..."
}

# Inyectar al prompt como con cartas
```

**Decisión:** implementar diccionario solo si keywords aparecen como fuente de fallos. Si no, queda en FUTURE_WORK.md.

## Eval con entity resolution

Re-correr el eval set con entity resolution activado. Comparar:

- Preguntas con `@mentions` vs preguntas sin
- Accuracy en card-specific questions: ¿mejoró?
- Latencia adicional: ¿cuánto agrega?
- Costo adicional: ¿cuántos tokens más por query?

## Tabla esperada en el blog post

| Tipo de pregunta | Baseline | Con Entity Resolution | Mejora |
|---|---|---|---|
| Card-specific | 0.62 | 0.87 | +25% |
| General rules | 0.81 | 0.81 | 0% |
| Multi-step | 0.71 | 0.74 | +3% |
| Edge cases | 0.55 | 0.58 | +3% |

(Números ilustrativos.)

**Insight clave:** entity resolution ayuda donde se espera, no donde no se espera. Eso es exactamente el tipo de hallazgo que querés contar.

## Criterio de "entity resolution implementada"

- [ ] Endpoint de autocomplete de cartas funciona
- [ ] Frontend muestra suggestions al tipear `@`
- [ ] Backend recibe y procesa card_mentions
- [ ] Prompt incluye texto de cartas mencionadas
- [ ] Eval re-corrido con entity resolution
- [ ] Comparación documentada
- [ ] Blog post tiene sección sobre esta decisión

## Anti-patterns a evitar

❌ Implementar Modo B (auto-detección) sin validar Modo A primero
❌ Inyectar TODOS los textos de cartas en cada query (token explosion)
❌ Skipear el eval comparativo
❌ Asumir que va a mejorar sin medir

✅ Implementar Modo A primero
✅ Solo inyectar las cartas mencionadas explícitamente
✅ Medir antes y después
✅ Documentar el trade-off en el blog post
