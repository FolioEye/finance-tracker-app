## graphify

This project has a knowledge graph at graphify-out/ with god nodes, community structure, and cross-file relationships.

Rules:
- For codebase questions, first run `graphify query "<question>"` when graphify-out/graph.json exists. Use `graphify path "<A>" "<B>"` for relationships and `graphify explain "<concept>"` for focused concepts. These return a scoped subgraph, usually much smaller than GRAPH_REPORT.md or raw grep output.
- If graphify-out/wiki/index.md exists, use it for broad navigation instead of raw source browsing.
- Read graphify-out/GRAPH_REPORT.md only for broad architecture review or when query/path/explain do not surface enough context.
- After modifying code, run `graphify update .` to keep the graph current (AST-only, no API cost).

## Context7 — library documentation

Before writing or reviewing code against an unfamiliar or version-sensitive library API (FastAPI, SQLAlchemy async, Pydantic v2, Alembic, asyncpg, React/Vite/Tailwind, Playwright, etc.), resolve the library via Context7 (`resolve-library-id` then `query-docs`) and check current docs rather than relying on training-data knowledge alone — especially for anything touching dependency versions, async/greenlet behavior, or recently-changed APIs. This caught real value once already: confirmed the `greenlet`/`sqlalchemy[asyncio]` pinning fix in PR #58 against the actual current SQLAlchemy 2.0 docs rather than just trusting the commit message.
