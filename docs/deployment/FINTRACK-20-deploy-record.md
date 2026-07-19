# Deploy Record: FinTrack API — FINTRACK-20 (Simple Budget Tracking)

**Date:** 2026-07-19 | **Deployer:** Monty (via Release Pro pass)

This is a record of a deploy that already happened, not a forward-looking
checklist — Railway auto-deploys `main` on every merge (see
ADR-005/ADR-007/ADR-008), so by the time this stage runs the production
container is already live. This doc exists to document what shipped, how
it was verified, and how to undo it if needed.

## What shipped

- 4 endpoints: `POST/GET/PATCH/DELETE /api/v1/budgets`
- Migration `0005_create_budgets_table.py` — new `budgets` table, additive
  only (no existing table altered, no backfill required)
- Architecture: `docs/adr/ADR-013-budget-tracking-compute-on-read.md`

## Pre-deploy state (verified before merge, not re-litigated here)

- [x] CI green on the merge commit's parent: Test Suite + Security Scan
  both passed (GitHub Actions run 29688825586)
- [x] Code reviewed — BA → Tech Lead → QA Lead gates all PASS, no STOP
  findings at any stage
- [x] No known critical bugs in release — the one real bug found
  (`percent_used` unquantized) was fixed by Tech Lead before handoff
- [x] Migration is backward-compatible and reversible — `downgrade()`
  cleanly drops the table, unique constraint, and index; no data loss
  risk since the table is brand new

## Deploy

- Merged PR #12 → squash commit `5c8d47c4b487cb4e4471762c2f2cb5ea83904f65`
  → Railway's GitHub integration auto-deployed `main` (its own trigger,
  not this workflow — see ADR-005)
- No GitHub Environments approval gate was involved: that gate only
  guards the frontend deploy job, which is skipped entirely until
  `apps/web` exists (no frontend has shipped for any FinTrack story yet)
- Migration executes as part of the container's own entrypoint
  (`alembic upgrade head && exec uvicorn ...`, see ADR-007/ADR-008) —
  same container, same environment, same log stream as the app itself,
  not a separate Railway Pre-Deploy Command

## Post-deploy verification

- [x] Railway deployment `780d23c0-bb8b-4cce-a3e6-e589518d39a3` on the
  `production` environment reports status **SUCCESS**, created
  2026-07-19T13:35:42.565Z (~2 seconds after the merge commit) — checked
  via Railway's own API, not just Monty's word
- [x] SUCCESS (rather than CRASHED) is itself evidence the migration step
  succeeded: the entrypoint runs `alembic upgrade head` before `exec
  uvicorn`, joined with `&&` — if the migration had failed, the container
  would never reach uvicorn and Railway would report CRASHED, not SUCCESS
- [ ] No live `GET /api/v1/budgets` smoke test was run against the
  production URL from this session — Railway's own deployment status is
  the verification signal used here, consistent with how FINTRACK-14
  through FINTRACK-17 were verified. If you want a direct HTTP smoke
  test against production, that's a manual step outside what this
  session did.

## Rollback

- **Trigger conditions:** error rate > 1%, p99 latency > 2s, `/health` or
  `/health/ready` failing
- **Command:** `git revert 5c8d47c4b487cb4e4471762c2f2cb5ea83904f65 && git push origin main`
  — Railway redeploys the reverted commit automatically
- **Rollback tag (previous known-good):** `4a003232082848bfc2688249276d6dd74624077b`
  (main's tip immediately before this merge)
- **Migration rollback:** only needed if reverting code alone isn't
  enough — `cd apps/api && alembic downgrade -1` drops the `budgets`
  table cleanly. Not required for a simple code revert, since the old
  code never queries a `budgets` table that doesn't exist yet in its own
  worldview; only needed if a later migration depends on 0005 and also
  needs undoing.
- Notify via Jira comment on FINTRACK-20 within 5 minutes of any rollback

## Known standing issue (unrelated to this deploy)

SCRUM Sprint 0's end date (2026-07-16) has passed while Jira still shows
it as "active" — flagged here for visibility since it affects sprint
reporting for every story, not just this one. Needs a manual close/new-
sprint action on the Jira board.
