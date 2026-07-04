# ADR-005: Railway (API) + Neon (DB) + Hostinger (Frontend)

**Status:** Accepted
**Date:** 2026-07-03
**Story:** FINTRACK-13 (first Release Pro pass — pipeline authored, first real deploy pending)
**Author:** Release Pro Agent

## Context

The blueprint (`Fintrack/BluePrint/AI_SDLC_Agent_Blueprint_FinanceTracker_v2.md`, Section 11)
specifies a split deployment: FastAPI backend on Railway, Postgres on Neon, static
React frontend on Hostinger. This ADR persists that decision inside the product
repo itself, alongside Tech Lead's ADR-004, rather than leaving it only in the
blueprint document.

## Decision

**Path A — split deployment, Railway native build (no GHCR).**

- **API (`apps/api`):** Railway. Connected directly to this GitHub repo; Railway
  builds from source on every push to `staging`/`main` — no Docker image push step,
  no GHCR storage.
- **Database:** Neon (managed Postgres, serverless scaling, DB branching for test
  environments, generous free tier). Connection string injected into Railway as
  `DATABASE_URL`.
- **Frontend (`apps/web`, not yet built):** Hostinger Premium Web Hosting (LiteSpeed).
  React/Vite static build, shipped via FTP from GitHub Actions.

## Reasons

FastAPI requires a persistent Python process — Hostinger's shared hosting plan
doesn't run one; Railway does, natively, from the connected GitHub repo. Hostinger's
LiteSpeed stack serves a static React SPA build well and is already paid for. Neon
gives managed Postgres without operating a database server. No GHCR needed —
Railway's native GitHub integration removes the Docker push step and any image
storage cost concerns entirely.

## Consequences

- Two independent deploy paths per push: Railway watches the repo directly (its own
  trigger, outside GitHub Actions); GitHub Actions owns the frontend build + FTP
  step + the `production` environment's human approval gate.
- `apps/web` does not exist yet — only backend stories have shipped so far. The
  frontend build/deploy jobs in `.github/workflows/ci-cd.yml` are guarded with
  `hashFiles('apps/web/package.json') != ''` so they skip cleanly instead of
  failing, and will start running automatically once a frontend story adds that
  directory. No workflow change needed at that point.
- Secrets live in two places by design, never in the repo: GitHub Secrets (`HOSTINGER_FTP_HOST`,
  `HOSTINGER_FTP_USER`, `HOSTINGER_FTP_PASS`, `VITE_API_URL`, `TEST_SECRET_KEY`) for
  the Actions-driven frontend deploy, and Railway's own environment variables
  (`DATABASE_URL`, `REDIS_URL`, `JWT_SECRET_KEY`, `FRONTEND_URL`) for the API,
  set directly in the Railway dashboard.
- Rollback for the API is a plain `git revert HEAD && git push origin main` —
  Railway redeploys automatically from the reverted commit. Rollback for the
  frontend is the previous `dist/` artifact re-run through the same FTP deploy
  step (see the pre-deployment checklist for the current known-good tag).
- The one-time Railway project/service setup (connecting the repo, creating
  `staging`/`main`-tracking services, setting env vars) happens in Railway's
  dashboard, not in this workflow file — Railway does not expose that as a
  GitHub Actions step. Same for Hostinger FTP credentials and GitHub Environment
  configuration (`staging`, `production` with required reviewers).
