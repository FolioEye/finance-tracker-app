# Deploy Record: FinTrack API — FINTRACK-22 (Threshold-Based Alerts)

**Date:** 2026-07-20 | **Deployer:** Monty (via Release Pro pass)

This is a record of a deploy that already happened, not a forward-looking
checklist — Railway auto-deploys `main` on every merge (see
ADR-005/ADR-007/ADR-008), so by the time this stage runs the production
container is already live. This doc exists to document what shipped, how
it was verified, and how to undo it if needed.

## What shipped

- `Alert` domain entity + `AlertRepository` port/adapter, migration
  `0006_create_alerts_table.py` — new `alerts` table, additive only (no
  existing table altered, no backfill required)
- `EvaluateAlertsForTransactionHandler` — write-time evaluation, called
  from `create_transaction`, isolated with try/except so an alert-side
  bug can never block a transaction write
- 2 endpoints: `GET /api/v1/alerts`, `POST /api/v1/alerts/{id}/dismiss`
- `TransactionRepository.get_recent_amounts_for_category` (new port
  method) backing the rolling-average large-transaction baseline
- Architecture: `docs/adr/ADR-014-threshold-alerts-write-time-detection.md`

## Pre-deploy state (verified before merge, not re-litigated here)

- [x] Full regression suite: 397/397 passed locally pre-merge (211 unit,
  91 security, 95 integration) — includes 53 new tests for this story
- [x] No live GitHub Actions status checks are configured on this repo
  (0 checks reported on the PR) — same as every prior FinTrack story
  this session; verification here relies on the local regression run,
  not a CI gate
- [x] Code reviewed — BA → Tech Lead → QA Lead gates all PASS, no STOP
  findings at any stage
- [x] One real bug found and fixed pre-merge during QA Lead pass: an
  integration test override was using a separate DB session from the
  one `create_transaction` used in the same request, causing alert
  evaluation to miss the not-yet-committed transaction row — fixed by
  sharing the per-request `get_db_session` dependency (test-only fix,
  no production code was wrong)
- [x] Migration is backward-compatible and reversible — `downgrade()`
  cleanly drops both unique constraints, the index, and the table; no
  data loss risk since the table is brand new

## Deploy

- Merged PR #14 → squash commit `12163a6ef15fc13ab700ce72c25de47fcf1ec157`
  → Railway's GitHub integration auto-deployed `main` (its own trigger,
  not this workflow — see ADR-005)
- No GitHub Environments approval gate was involved: that gate only
  guards the frontend deploy job, which is skipped entirely until
  `apps/web` exists (no frontend has shipped for any FinTrack story yet)
- Migration executes as part of the container's own entrypoint
  (`alembic upgrade head && exec uvicorn ...`), same as every prior
  migration this project

## Post-deploy verification

- [x] Railway deployment `ea236644-5005-42c6-9c9b-0b3436e4f437` on the
  `production` environment reports status **SUCCESS**, created
  2026-07-20T01:29:10.184Z on commit `12163a6e...` — the exact merge
  commit, checked via Railway's own API
- [x] SUCCESS is itself evidence the migration step succeeded: the
  entrypoint runs `alembic upgrade head` before `exec uvicorn`, joined
  with `&&` — a migration failure would leave the container CRASHED, not
  SUCCESS
- [x] Independently re-ran the full regression suite (211 unit + 91
  security + 95 integration = 397 tests) against a fresh clone of `main`
  at the merge commit, not just re-trusting the pre-merge local run —
  397/397 passed
- [ ] No live `GET /api/v1/alerts` smoke test was run against the
  production URL from this session — Railway's own deployment status is
  the verification signal used here, consistent with FINTRACK-14 through
  FINTRACK-20. If you want a direct HTTP smoke test against production,
  that's a manual step outside what this session did.

## Rollback

- **Trigger conditions:** error rate > 1%, p99 latency > 2s, `/health` or
  `/health/ready` failing
- **Command:** `git revert 12163a6ef15fc13ab700ce72c25de47fcf1ec157 && git push origin main`
  — Railway redeploys the reverted commit automatically
- **Rollback tag (previous known-good):** `7ecd63f9697e92d96934ecda4b1bf6f36f385a94`
  (main's tip immediately before this merge — FINTRACK-20's deploy record commit)
- **Migration rollback:** only needed if reverting code alone isn't
  enough — `cd apps/api && alembic downgrade -1` drops the `alerts`
  table cleanly. Not required for a simple code revert, since the old
  code never queries an `alerts` table that doesn't exist yet in its own
  worldview; only needed if a later migration depends on 0006 and also
  needs undoing.
- Notify via Jira comment on FINTRACK-22 within 5 minutes of any rollback

## Known standing issue found during this pass (unrelated to this deploy)

The Railway project's **staging** environment crashed on this same
commit (deployment `0f3d0407-4fcf-4210-b214-b0548b3f3a2b`, status
CRASHED) — root cause is missing required env vars (`database_url`,
`jwt_secret_key` both report as `Field required` in the Pydantic
Settings validation error), not anything in this story's code. This is
a pre-existing gap in the staging environment's configuration, not a
regression introduced here — production has both vars set correctly and
deployed clean on the identical commit. Also worth noting: both the
staging and production Railway environments are triggering off pushes to
`main` (per each deployment's `meta.branch: "main"`), not staging off a
dedicated `staging` branch as ADR-005/the Release Pro skill's pipeline
shape describes — worth a manual look at the Railway project's branch
trigger config. Neither issue blocks this story's release since
production is healthy; flagged here for visibility, not treated as
resolved by this pass.
