# ADR-004 — Entity Resolution: Deferred to v2 (Data-Driven Decision)

**Status**: Accepted  
**Date**: 2026-05-15  
**Authors**: Gonzalo Asencio

---

## Context

The Riftbound rulebook contains references to specific card names (e.g., "Quick Strike", "Veilbreaker") which may appear in user queries. A user asking "what does Veilbreaker do?" is making a card-specific entity query — not a general rules question. The hypothesis was that resolving these entities (detecting card names in the query, injecting card-specific text from a cards database) would improve retrieval quality for this query category.

Two implementation modes were considered (documented in `Specs/07_entity_resolution_spec.md`):
- **Mode A** (`@mentions`): user explicitly tags card names in the query UI with an `@` prefix
- **Mode B** (fuzzy auto-detect): NLP-based card name detection in the query string

The eval spec (`Specs/07`) defined the threshold for building entity resolution: implement only if card-specific query failures exceed 20% of the category in the evaluation set.

At v1 launch, no RAGAS eval run has been completed. The eval set exists but has not been executed against the live pipeline.

---

## Decision

Defer entity resolution. Do not implement Mode A or Mode B in v1.

The forward hook is in place: `card_mentions: list[str] | None` is threaded through `pipeline.answer_question()` and used as part of the cache key (`backend/app/cache.py`). This means entity resolution can be added later without touching the pipeline signature or cache invalidation logic.

The decision to skip was data-driven by absence, not by preference: without eval numbers showing card-specific failure rates, building entity resolution optimizes for a hypothesis rather than a measured problem.

---

## Alternatives Considered

| Option | Reason rejected |
|---|---|
| Build Mode A now (`@mentions` UI) | No baseline failure data to justify the UI complexity. Adds frontend scope without evidence of user need. |
| Build Mode B (fuzzy NLP detection) | Fuzzy card name detection has a high false positive risk — a user asking "what is quick play?" could trigger a card lookup for a different card named "Quick". Without an eval set validating the detection accuracy, false positives would degrade answer quality. |
| Build a cards database and inject card text | Requires a separate ingestion pipeline and data source. High implementation cost with no measured benefit. |

---

## Consequences

✅ Zero scope creep in v1 — avoids building infrastructure for an unvalidated hypothesis.  
✅ Forward hook already wired — `card_mentions` flows through pipeline and cache key, so Mode A can be added as a UI + prompt injection change without rearchitecting the backend.  
✅ Decision is reversible — the threshold from `Specs/07` is clear: run the eval set, check card-specific failure rate. If > 20%, build it.  

❌ Card-specific queries in v1 rely on rulebook chunks alone. If the rulebook does not contain the full card text, answers may be incomplete or wrong for card-attribute questions.  
❌ Config D (+ Entity Resolution) row in the results table remains "not implemented" — the eval comparison will be incomplete until Mode A is built and evaluated.  
❌ Users have no way to explicitly anchor a query to a specific card in the v1 UI — the `@mentions` affordance does not exist yet.
