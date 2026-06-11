# 08 - Frontend Specification

## Filosofía

**Una pantalla principal + un tab de Rules.** Eso es todo.

El frontend no es el portfolio. El RAG es el portfolio. El frontend solo tiene que:
1. No verse mal
2. No romperse
3. Mostrar las citas con prominencia (es la estrella técnica)

## Layout general

```
┌─────────────────────────────────────────────────┐
│  Riftbound Judge AI                  [Rules] [GH]│
├─────────────────────────────────────────────────┤
│                                                 │
│  Ask a rules question:                          │
│  ┌───────────────────────────────────────┐     │
│  │ Can I block with @Ahri if @Garen...   │     │
│  └───────────────────────────────────────┘     │
│                              [ Ask Judge ]      │
│                                                 │
│  ─────────────────────────────────────────      │
│                                                 │
│  💡 Try these:                                  │
│  [Can I sacrifice my legend?]                   │
│  [How does Hunt resolve at end of turn?]        │
│  [What if both players attack the same...]      │
│                                                 │
│  ─────────────────────────────────────────      │
│                                                 │
│  Answer:                                        │
│  ────────                                       │
│  Based on the rules, [answer text streamed].   │
│                                                 │
│  Confidence: ●●○ Medium                         │
│                                                 │
│  📚 Sources:                                    │
│  ┌─────────────────────────────────────────┐   │
│  │ Core Rules §4.2 "Blocking"               │   │
│  │ "A defending player declares blockers..."│   │
│  │                              [View →]    │   │
│  └─────────────────────────────────────────┘   │
│  ┌─────────────────────────────────────────┐   │
│  │ Card: Garen "Quick Strike"               │   │
│  │ "Quick Strike: This unit deals damage..."│   │
│  └─────────────────────────────────────────┘   │
│                                                 │
│  [👍 Helpful]  [👎 Not helpful]  [🚩 Wrong]    │
│                                                 │
└─────────────────────────────────────────────────┘
```

## Páginas (App Router de Next.js)

```
app/
├── layout.tsx              # Root layout con navbar
├── page.tsx                # Pantalla principal (judge)
├── rules/
│   └── page.tsx            # Tab Rules
├── api/                    # API routes (proxy a FastAPI)
│   └── query/
│       └── route.ts
└── components/
    ├── QueryInput.tsx
    ├── AnswerDisplay.tsx
    ├── CitationsList.tsx
    ├── ConfidenceBadge.tsx
    ├── FeedbackButtons.tsx
    ├── ExampleQueries.tsx
    └── CardMentionAutocomplete.tsx  # solo si entity resolution
```

## Componentes detallados

### QueryInput

- Text input controlado
- Soporta `@mentions` si entity resolution está implementado
- Submit por Enter o botón
- Loading state mientras espera respuesta
- Deshabilitado durante streaming

### AnswerDisplay

- Recibe respuesta streameada del backend
- Renderiza Markdown (negritas, listas, etc.)
- Muestra "..." mientras streamea
- Si `defer_to_judge=true`, muestra mensaje destacado y oculta confidence

### CitationsList

**Esto es la estrella visual del portfolio.**

- Lista de cards (componente shadcn/ui)
- Cada card muestra:
  - Tipo de fuente (rulebook / faq / errata / card)
  - Sección o nombre de carta
  - Quote relevante (snippet del chunk)
  - Botón "View →" que linkea al tab Rules con scroll a esa sección
- Hover muestra el chunk completo

### ConfidenceBadge

- 3 niveles: ●●● High, ●●○ Medium, ●○○ Low
- Colors: green / yellow / red
- Tooltip explica qué significa cada nivel

### FeedbackButtons

- 3 botones: 👍 Helpful, 👎 Not helpful, 🚩 Wrong
- Al click, POST a `/api/v1/feedback` con query_id
- Después del feedback, muestra "Thanks!" y se deshabilita
- No requiere auth

### ExampleQueries

- 3 botones con queries pre-definidas
- Al click, llenan el input y disparan submit
- **Crítico para demos en entrevistas:** estos 3 ejemplos demuestran:
  1. Una pregunta donde el sistema brilla
  2. Una pregunta multi-step que muestra razonamiento
  3. Una pregunta donde el sistema correctamente dice "consultá juez"

## Tab Rules

### Layout

```
┌─────────────────────────────────────────────────┐
│  ← Back to Judge                                │
├─────────────────────────────────────────────────┤
│                                                 │
│  ┌──────────────┐  ┌──────────────────────┐    │
│  │ Table of     │  │  # Riftbound Rules    │    │
│  │ Contents     │  │                       │    │
│  │              │  │  ## 1. Game Overview  │    │
│  │ 1. Overview  │  │  [content...]         │    │
│  │ 2. Setup     │  │                       │    │
│  │ 3. Turn      │  │  ## 2. Setup          │    │
│  │ 4. Blocking  │  │  [content...]         │    │
│  │ 5. Combat    │  │                       │    │
│  │ ...          │  │  ...                  │    │
│  │              │  │                       │    │
│  └──────────────┘  └──────────────────────┘    │
│                                                 │
└─────────────────────────────────────────────────┘
```

### Implementación

```tsx
// app/rules/page.tsx

import fs from 'fs';
import ReactMarkdown from 'react-markdown';
import rehypeSlug from 'rehype-slug';
import rehypeAutolinkHeadings from 'rehype-autolink-headings';
import remarkGfm from 'remark-gfm';

export default async function RulesPage({ searchParams }) {
  const content = fs.readFileSync('data/rulebook.md', 'utf-8');
  
  return (
    <div className="flex">
      <TableOfContents content={content} />
      <article className="prose max-w-none">
        <ReactMarkdown
          rehypePlugins={[rehypeSlug, rehypeAutolinkHeadings]}
          remarkPlugins={[remarkGfm]}
        >
          {content}
        </ReactMarkdown>
      </article>
    </div>
  );
}
```

**Features:**
- TOC auto-generado de los headers del Markdown
- Anchor links en cada section (URL: `/rules#section-4-2`)
- Búsqueda dentro de la página con Ctrl+F (nativa del browser, no implementamos)
- Scroll suave a sección cuando se llega via URL fragment

**Lo que NO hace el tab Rules:**
- ❌ No tiene búsqueda custom
- ❌ No tiene filtros
- ❌ No tiene edición
- ❌ No es editable
- ❌ No tiene navegación complicada
- ❌ No tiene comentarios

Es **solo render del Markdown** con TOC. Eso es todo.

## Streaming

Usar Vercel AI SDK para streamear la respuesta:

```tsx
// app/api/query/route.ts

import { StreamingTextResponse } from 'ai';

export async function POST(req: Request) {
  const { question, card_mentions } = await req.json();
  
  const response = await fetch(`${API_URL}/api/v1/query`, {
    method: 'POST',
    body: JSON.stringify({ question, card_mentions }),
  });
  
  // Stream del backend al frontend
  return new StreamingTextResponse(response.body);
}
```

## Mobile responsive

**Mínimo aceptable:**
- Funciona en pantalla 375px wide (iPhone SE)
- TOC del tab Rules se vuelve collapsible en mobile
- Input grande, fácil de tocar
- Citas legibles

**No buscamos:**
- Animaciones complejas
- Gestos custom
- PWA install

## Estilo

Usar shadcn/ui como base. Customizar mínimamente:

- Tipografía: default (Inter o similar)
- Colors: default neutral
- Espaciado: generoso (legibilidad > densidad)
- Modo oscuro: opcional, si shadcn/ui lo da gratis

**No invertir tiempo en diseño visual sofisticado.** El layout claro y funcional es suficiente.

## Criterio de "frontend listo"

- [ ] Deployed en Vercel
- [ ] URL pública funciona
- [ ] Pantalla principal: input → respuesta → citas → feedback completo
- [ ] Streaming visible
- [ ] Tab Rules renderiza completo
- [ ] Citas linkean al tab Rules
- [ ] 3 example queries cargadas y funcionando
- [ ] Mobile responsive aceptable
- [ ] No hay errores en consola

## Anti-patterns a evitar

❌ Tiptap u otro rich editor (overkill)
❌ Animaciones de loading complejas
❌ Modo oscuro custom desde cero
❌ Custom design system
❌ Más de 2 colores de acento
❌ Sidebar persistente con menu de features

✅ Componentes shadcn/ui out-of-the-box
✅ Tailwind utility classes
✅ Mobile-first responsive
✅ Citas siempre visibles (no escondidas en drawer)
