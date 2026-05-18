# Portfolio Polish — Content Specification

## Purpose

This spec defines what MUST be true about each documentation deliverable after the `portfolio-polish` change is merged. No code behavior changes. All requirements describe content correctness, completeness, and honesty constraints.

---

## Requirements

### Requirement: README Completeness

The root `README.md` MUST contain all of the following sections, in any order: one-liner tagline, hero image placeholder, live demo link, architecture section with an embedded Mermaid diagram, results table, key decisions section with links to ADRs, setup instructions (backend and frontend), evaluation methodology section, what's next section.

The README MUST NOT contain fabricated evaluation numbers. Any metric without a measured value MUST be marked `TBD`.

#### Scenario: New-developer onboarding

- GIVEN a developer with no prior context about the project opens the repository
- WHEN they read only the README
- THEN they can answer: what the project does, which stack it uses, what architectural decisions were made, and how to run it locally — without opening any other file

#### Scenario: Local setup in 30 minutes

- GIVEN a clean machine with Python and Node.js installed
- WHEN the developer follows the README setup instructions verbatim
- THEN the backend and frontend are running locally within 30 minutes

#### Scenario: Missing eval data

- GIVEN one or more retrieval configurations have not yet been benchmarked
- WHEN the README results table is rendered
- THEN the missing cells show `TBD` — no invented numbers appear

---

### Requirement: Architecture Diagram

The README MUST embed a Mermaid diagram that shows the request path: user → Next.js/Vercel → FastAPI → rate limiter → cache → RAG pipeline → pgvector + Gemini.

The diagram MUST also show the ingestion flow: corpus → embeddings → pgvector.

The diagram MUST show the observability layer: Langfuse and Sentry.

#### Scenario: Diagram renders in GitHub

- GIVEN the README is viewed on github.com
- WHEN the Mermaid code block is parsed
- THEN the diagram renders without syntax errors

#### Scenario: All system components visible

- GIVEN the rendered diagram
- WHEN a reviewer inspects it
- THEN every component listed in the requirement (rate limiter, cache, RAG pipeline, pgvector, Gemini, Langfuse, Sentry) is present as a labeled node or annotation

---

### Requirement: Results Table

The README MUST include a results table with columns: Configuration, Faithfulness, Answer Relevancy, Context Precision, Context Recall, p95 Latency, Cost/query.

The table MUST have at minimum two rows: "Baseline (vector only)" and "Hybrid (dense + FTS)".

The table MUST be accompanied by a methodology footnote that states: eval set size, eval methodology (tool/framework used), and run conditions (hardware or environment).

#### Scenario: Table with partial data

- GIVEN not all configurations have been benchmarked
- WHEN the results table is authored
- THEN rows with missing values use `TBD` cells — no cells are left blank or contain invented numbers

#### Scenario: Methodology footnote present

- GIVEN the results table
- WHEN a reader reviews the table
- THEN a footnote or sub-section immediately following the table describes how the evals were run

---

### Requirement: ADRs

A minimum of 5 Architecture Decision Records MUST exist under `docs/adrs/`.

The required ADRs are:
- ADR-001: bge-m3 vs OpenAI embeddings
- ADR-002: pgvector vs dedicated vector DB
- ADR-003: hybrid retrieval tradeoff
- ADR-004: entity resolution decision (data-driven)
- ADR-005: Gemini Flash choice

Each ADR MUST contain three sections: Context, Decision, Consequences. The Consequences section MUST list at least one pro (marked ✅) and at least one con (marked ❌).

#### Scenario: ADR renders correctly

- GIVEN any ADR file under `docs/adrs/`
- WHEN it is opened in a Markdown viewer
- THEN Context, Decision, and Consequences sections are all present and non-empty

#### Scenario: ADR linked from README

- GIVEN the README key decisions section
- WHEN a reader follows any ADR link
- THEN the link resolves to the correct ADR file in the repository

#### Scenario: All 5 required ADRs present

- GIVEN the `docs/adrs/` directory
- WHEN its contents are listed
- THEN files for all 5 required ADRs exist

---

### Requirement: Blog Post Draft

A blog post draft MUST exist at `docs/blog/post.md` (or `docs/blog/riftbound-rag-post.md`).

The post MUST be between 1500 and 2500 words.

The post MUST follow this structure in order: hook, problem, approach, eval set description, baseline results, ablation / configuration comparison, entity resolution decision, surprises or unexpected findings, what I'd do differently, tech stack summary, try-it call to action.

The post MUST NOT contain marketing language or fabricated numbers. All claims MUST be grounded in the actual system or marked as estimates.

#### Scenario: Word count within range

- GIVEN the blog post file
- WHEN its word count is measured
- THEN the count is between 1500 and 2500 words (inclusive)

#### Scenario: Required sections all present

- GIVEN the blog post
- WHEN a reviewer reads it
- THEN all 11 required structural sections are identifiable in order

#### Scenario: No fabricated metrics

- GIVEN the blog post contains performance claims
- WHEN each claim is cross-referenced with the results table in the README
- THEN every numeric claim either matches a measured value in the table or is explicitly labeled as an estimate or TBD

---

### Requirement: FUTURE_WORK.md

`FUTURE_WORK.md` MUST exist at the repository root.

It MUST include entries for: streaming responses, multi-language support, feedback loop (thumbs up/down → fine-tuning signal), entity resolution (if not yet implemented), cost optimization strategies.

#### Scenario: File exists at root

- GIVEN the repository root
- WHEN the file listing is checked
- THEN `FUTURE_WORK.md` is present

#### Scenario: All required topics covered

- GIVEN `FUTURE_WORK.md`
- WHEN its contents are reviewed
- THEN all 5 required topics appear as named entries

---

### Requirement: LICENSE

A `LICENSE` file MUST exist at the repository root containing standard MIT License text.

The license MUST specify year 2026 and author name Gonzalo Asencio.

#### Scenario: License file present and correct

- GIVEN the repository root
- WHEN `LICENSE` is opened
- THEN it contains MIT License text with year 2026 and "Gonzalo Asencio" as the copyright holder

---

### Requirement: Demo Queries Document

A demo queries document MUST exist at `docs/demo-queries.md`.

It MUST contain exactly 5 queries, each accompanied by expected behavior notes describing what a correct response looks like and any edge case behavior to verify.

The 5 queries MUST cover distinct categories: at minimum one easy factual query, one multi-step or multi-entity query, one card-specific lookup, one edge case (obscure or ambiguous), and one adversarial or prompt-injection attempt.

#### Scenario: All 5 queries with notes

- GIVEN `docs/demo-queries.md`
- WHEN its contents are reviewed
- THEN 5 queries are present, each with at least one sentence of expected behavior notes

#### Scenario: Category coverage

- GIVEN the 5 queries
- WHEN they are categorized
- THEN at least one query falls into each of the 5 required categories

---

### Requirement: No Code Changes

No files under `backend/app/`, `backend/scripts/`, or `frontend/src/` MUST be modified by this change.

#### Scenario: PR diff is documentation only

- GIVEN the pull request for this change
- WHEN the diff is inspected
- THEN every changed file is a `.md`, `LICENSE`, or documentation asset — no Python, TypeScript, or configuration files under the backend or frontend source trees appear in the diff
