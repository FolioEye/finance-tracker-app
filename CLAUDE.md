## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Context7 — library documentation

Before writing or reviewing code against an unfamiliar or version-sensitive library API (FastAPI, SQLAlchemy async, Pydantic v2, Alembic, asyncpg, React/Vite/Tailwind, Playwright, etc.), resolve the library via Context7 (`resolve-library-id` then `query-docs`) and check current docs rather than relying on training-data knowledge alone — especially for anything touching dependency versions, async/greenlet behavior, or recently-changed APIs. This caught real value once already: confirmed the `greenlet`/`sqlalchemy[asyncio]` pinning fix in PR #58 against the actual current SQLAlchemy 2.0 docs rather than just trusting the commit message.

## FinTrack SDLC pipeline — role skills live in the anthropic-skills plugin

This repo's SDLC pipeline (PM → BA → Tech Lead → QA Lead → Release Pro, with
Gatekeeper checkpoints — enforced server-side by the `gforce` orchestrator's
Jira-transition-mediation and tool-allowlist checks) is driven by the
`anthropic-skills` plugin's `fintrack-pm`, `fintrack-ba`, `fintrack-tech-lead`,
`fintrack-qa-lead`, `fintrack-release-pro`, and `gatekeeper` skills —
project-specific instantiations of that plugin's generic `sdlc-*` templates
(see `orchestrator/config.py`'s own comment referencing
"sdlc-tech-lead/sdlc-qa-lead/sdlc-pm"). Use those skills for pipeline-stage
work rather than reimplementing PM/BA/Tech-Lead/QA/Release logic ad hoc.

The separate `approve-and-advance` skill (in the `AgenticOSRoutine` repo) is
the client-side action that signs Mehul's explicit stage approval and posts
it to this orchestrator — it does not perform any pipeline-stage work itself.
