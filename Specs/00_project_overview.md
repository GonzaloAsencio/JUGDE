# 00 - Project Overview

> **Status (histórico):** Plan original del proyecto. Algunas decisiones
> pivotearon durante la implementación — sobre todo la evaluación, que pasó de
> RAGAS a un harness LLM-as-judge (ver **ADR-006**), y el orden del roadmap, que
> se construyó "al revés" (pipeline → frontend → hardening → eval). Para el
> estado real, ver el **README** y los **ADRs**. Esta spec se conserva como
> registro del diseño inicial.

## Qué es esto

Un asistente RAG (Retrieval-Augmented Generation) para responder preguntas de reglas del juego de cartas Riftbound (Riot Games).

## Para qué es esto

**Portfolio rápido que demuestre skills de RAG engineering** para entrevistas de trabajo en posiciones de AI/ML Engineer, LLM Engineer, o Full-Stack con AI.

## Para qué NO es esto

- No es un producto comercial
- No es un reemplazo de jueces de torneo
- No es una app con usuarios reales como objetivo principal
- No es un proyecto open-source para mantener largo plazo

## Métricas de éxito

**Métricas técnicas** (lo que demuestra al recruiter):
- Eval set de 40-60 preguntas con respuestas canónicas
- Tabla comparativa de al menos 3 configuraciones de retrieval con números reales
- Live demo URL funcional
- README con architecture diagram + decision log
- 1 blog post técnico publicado

**Métricas NO buscadas:**
- Cantidad de usuarios
- Revenue
- Feature parity con competidores
- 100% accuracy

## Restricciones

- **Duración:** 6 semanas (no negociable)
- **Costo cash:** $0-12/mes durante desarrollo
- **Trabajo:** solo developer (vos)
- **Stack:** Python backend + Next.js frontend (decidido, no se debate)

## Por qué Riftbound y no otro TCG

- Juego nuevo (lanzado 2025): no hay competencia en GitHub
- Corpus chico: reglamento curatable en un fin de semana
- Comunidad activa: feedback potencial si quisiéramos
- Decisión cerrada: no se debate más

## Filosofía de escalabilidad

El stack se escala **cambiando sliders en dashboards**, no reescribiendo código:
- Free tier soporta <500 usuarios sin tocar código
- Upgrade a paid tier ($25-50/mes) soporta hasta ~5000 usuarios
- Más allá de eso: problema bueno de tener, se ataca cuando se llegue

**No construimos infraestructura para usuarios que no existen.**

## Lo que NO está incluido

Ver `FUTURE_WORK.md` para la lista completa. Resumen de lo principal excluido:

- Tournament mode
- PWA / offline mode
- Recent questions / historial persistente
- Tab Cards (browse de cartas)
- Tags clickeables en respuestas
- Auth de usuarios
- Multi-idioma día 1
- Community features

## Definición de "terminado"

El proyecto está terminado cuando:

1. Live demo URL responde a preguntas y muestra citas
2. README tiene tabla de resultados con números reales
3. Blog post está publicado
4. Repo GitHub está limpio y reproducible
5. Puedo contar la historia en 30 segundos en una entrevista

**No está terminado si:**
- "Falta una feature más"
- "Quiero mejorar X"
- "Y si agrego Y"

Esas cosas van a `FUTURE_WORK.md` y se hacen después de declarar terminado.
