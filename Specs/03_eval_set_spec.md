# 03 - Eval Set Specification

## Por qué esta spec existe primera

Sin eval set, no podés:
- Comparar configuraciones de retrieval
- Justificar decisiones técnicas con datos
- Detectar regresiones
- Tener una historia que contar en el blog post

**El eval set es el activo de mayor ROI del proyecto.** Más que el código.

## Objetivo

Construir un conjunto de 40-60 preguntas representativas, con:
- Respuestas canónicas verificadas
- Citas exactas al corpus
- Clasificación por dificultad
- Distribución que permita medir fallos por categoría

## Por qué 40-60 y no 200

- 40 preguntas BIEN hechas > 200 mediocres
- Cada pregunta bien hecha lleva 10-20 minutos
- 50 preguntas × 15 min = 12 horas de trabajo focalizado
- Más allá de 60, los retornos decrecen para un proyecto solo-dev

## Schema de cada pregunta

```json
{
  "id": "uuid",
  "question": "string (como la haría un jugador real)",
  "canonical_answer": "string (respuesta correcta y completa)",
  "source": {
    "document": "rulebook | faq | errata",
    "section": "string (ej: '4.2 Blocking')",
    "page": "integer (opcional)"
  },
  "difficulty": "factual_direct | multi_step | edge_case",
  "category": {
    "mentions_specific_cards": "boolean",
    "mentions_keywords": "boolean",
    "requires_card_text": "boolean",
    "requires_multiple_sources": "boolean"
  },
  "expected_behavior": "answer | defer_to_judge",
  "notes": "string (opcional, para tu referencia)"
}
```

## Distribución objetivo

De las 50 preguntas, apuntar a:

| Categoría | Cantidad | Por qué |
|---|---|---|
| Factual directa (1 fuente) | 15-20 | Caso fácil, baseline funciona |
| Multi-step reasoning | 15-20 | Donde RAG mejor brilla |
| Edge cases | 5-10 | Donde el sistema debe decir "consultá juez" |
| Mencionan cartas específicas | 15-20 | Para medir si necesitamos entity resolution |
| Mencionan keywords técnicos | 10-15 | Para medir si necesitamos dictionary |
| Sin respuesta clara | 3-5 | Para testear calibración de confianza |

## Proceso de curación

### Paso 1: Inmersión en el reglamento (2-3 horas)
- Leer el reglamento completo una vez
- Anotar conceptos que parezcan confusos o multi-step
- Anotar términos técnicos (keywords)

### Paso 2: Recolección de preguntas reales (2-3 horas)
- Reddit r/Riftbound: buscar threads "rules question"
- Discord oficial: canal de reglas si hay acceso
- Reviews de YouTube de torneos: preguntas que jugadores hacen
- Notar las que se repiten

### Paso 3: Draft inicial solo (4-6 horas)
- Escribir 50 preguntas en un Google Doc
- Para cada una: respuesta + cita
- No buscar perfección, buscar volumen draft

### Paso 4: Validación
- Releer cada una: ¿es responible desde el corpus?
- Validar al menos 20 con un jugador experimentado si posible
- Marcar 3-5 como "sin respuesta clara" para testear deferral

### Paso 5: Estructurar
- Convertir Google Doc a `data/eval_set.json`
- Validar schema
- Generar IDs únicos

## Estructura de archivo

```
backend/
└── data/
    ├── eval_set.json           # Las 50 preguntas estructuradas
    ├── eval_set_metadata.json  # Stats sobre el eval set
    └── eval_runs/              # Resultados de cada run
        ├── 2026-05-20_baseline.json
        ├── 2026-05-22_hybrid.json
        └── ...
```

## Validación del eval set

Antes de usar el eval set para experimentar, validar:

- [ ] Todas las preguntas tienen respuesta canónica
- [ ] Todas las respuestas tienen cita verificable
- [ ] Distribución de categorías cumplida
- [ ] Al menos 3 preguntas marcadas como "no tiene respuesta clara"
- [ ] Schema válido (JSON parsea sin errores)

## Anti-patterns a evitar

❌ Preguntas que vos sabés que el sistema va a responder bien
❌ Preguntas con respuestas vagas que admiten múltiples lecturas
❌ Preguntas que requieren información fuera del corpus
❌ Preguntas que dependen de cartas no incluidas en tu DB

✅ Preguntas que un jugador real haría
✅ Preguntas con respuesta inequívoca según fuente oficial
✅ Mezcla de fácil y difícil
✅ Algunas donde la respuesta correcta es "no se puede determinar"

## Tarea inmediata (esta semana)

**Antes de hacer cualquier código:**

1. Descargar reglamento oficial PDF
2. Crear `data/eval_set.json` con las primeras 10 preguntas
3. Mostrar las primeras 10 para feedback antes de continuar al resto

Si las primeras 10 las hacés bien en una tarde, el proyecto es viable.
Si te trabás, paramos y rediscutimos antes de seguir.
