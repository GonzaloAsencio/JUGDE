# Proposal: Portfolio Polish + Launch

## Intent

The codebase is functionally complete, but **functional code is not a portfolio**. Without packaging, this project will not generate interviews. A recruiter or hiring engineer needs to answer four questions in 90 seconds of repo skimming: *what does it do, how does it work, what decisions were made, does the author understand them?*. This change builds the documentation and content assets that answer those questions so the project becomes a hiring asset.

## Scope

### In Scope
- Root `README.md` with one-liner, hero asset, live demo + blog + video links, architecture diagram, results table, ADR summaries, setup, evaluation methodology, credits
- Mermaid architecture diagram embedded in README (user → Next.js → FastAPI → pgvector + Gemini + observability)
- Comparative results table with real numbers across 3-4 retrieval configurations (faithfulness, answer relevancy, context precision, context recall, p95 latency, cost/query) plus methodology footnote
- At least 5 ADRs under `docs/adrs/` (bge-m3 vs OpenAI, pgvector vs dedicated vector DB, hybrid retrieval tradeoff, entity resolution decision, Gemini Flash choice)
- Blog post draft (1500-2500 words) committed to `docs/blog/` and ready to publish to Medium/Dev.to/Hashnode
- Demo script with 5 prepared queries (easy, multi-step, card-specific, edge case, prompt injection) in `docs/demo-script.md`
- Video demo recording brief / shot list in `docs/video-script.md` (3-min target). Actual recording is out of scope.
- `FUTURE_WORK.md` at repo root
- `LICENSE` (MIT) at repo root
- LinkedIn/X launch post draft in `docs/launch-posts.md`

### Out of Scope
- New code, refactors, or feature work — the codebase is frozen for this change
- Re-running the eval pipeline; we use existing measured numbers (if any are missing, that gap is flagged, not filled by code changes)
- Recording the video or publishing the blog/social posts (humans-in-the-loop after merge)
- Setting up Vercel/Render deploys for the live demo URL — assumes URLs already exist or will be supplied

## Capabilities

### New Capabilities
- None — this change ships no behavior.

### Modified Capabilities
- None — no requirements change.

## Approach

Treat this as a documentation packaging sprint, not engineering. One PR ships every artifact together so reviewers and the launch surface stay consistent. Reuse decisions and numbers already produced by prior changes (`production-hardening`, eval pipeline). Where a real number is unavailable, mark as `TBD` rather than inventing data. ADRs follow the short Context / Decision / Consequences template. The README is the centerpiece; every other artifact links from it.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `README.md` (root) | New | Portfolio-facing README replacing nothing (none currently at root) |
| `docs/adrs/` | New | 5 ADR markdown files |
| `docs/blog/riftbound-rag-post.md` | New | Long-form technical post |
| `docs/demo-script.md` | New | 5 demo queries with expected behavior |
| `docs/video-script.md` | New | 3-min shot list and talking points |
| `docs/launch-posts.md` | New | LinkedIn + X copy |
| `FUTURE_WORK.md` | New | Deferred work backlog |
| `LICENSE` | New | MIT |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| Eval numbers for some configs are missing | Med | Use `TBD` markers and flag in tasks; do not fabricate metrics |
| Live demo URL not yet provisioned | Med | Use placeholder link with note; do not block PR on infra |
| README drifts from reality after future code changes | Low | Single source of truth for stack table; reference ADRs by ID |
| Scope creep into code fixes during writing | Med | Hard rule in design phase: any code finding becomes a FUTURE_WORK entry, not a commit |

## Rollback Plan

This is additive content. Rollback = `git revert` the merge commit. No data, schema, or runtime surface is touched. Frontend and backend continue to work unchanged.

## Dependencies

- Existing eval results from prior measurement runs (or explicit `TBD` markers)
- Live demo URL (placeholder acceptable for first pass)
- Hero screenshot or GIF asset (can be captured during this change or referenced as TBD)

## Success Criteria

- [ ] A reviewer with zero prior context can answer "what does it do / how does it work / what decisions were made" in under 90 seconds from the README
- [ ] Setup instructions reproduce a working local environment in under 30 minutes on a clean machine
- [ ] Results table contains methodology footnote (eval set size, composition, run count)
- [ ] At least 5 ADRs committed under `docs/adrs/`
- [ ] `LICENSE`, `FUTURE_WORK.md`, blog draft, demo script, video script, launch posts all committed
- [ ] No code under `backend/app/`, `backend/scripts/`, or `frontend/src/` modified in the resulting PR
