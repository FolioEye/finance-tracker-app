# Deploy Checklist: FinTrack API — FINTRACK-13 (User Registration), first-ever release

**Date:** 2026-07-03 | **Deployer:** Monty

This is the **first deployment for this repo** — no CI/CD pipeline, GitHub
Environments, or hosting connections exist yet. Most of this checklist is
therefore one-time setup, not a routine pre-deploy check. Once done, later
stories (FINTRACK-14 onward) skip straight to the routine section.

## One-time setup (do before the first push of this workflow)

- [ ] **GitHub Secrets** (repo Settings → Secrets and variables → Actions) — add:
  - `TEST_SECRET_KEY` — any random string, test runs only
  - `HOSTINGER_FTP_HOST`, `HOSTINGER_FTP_USER`, `HOSTINGER_FTP_PASS` — from your Hostinger hPanel FTP account
  - `VITE_API_URL` — your Railway API's public URL, once created (placeholder is fine until then, frontend build is skipped anyway — see ADR-005)
- [ ] **GitHub Environments** (repo Settings → Environments):
  - Create `staging` — no required reviewers
  - Create `production` → enable **Required reviewers** → add yourself
- [ ] **Railway** (railway.app dashboard):
  - New Project → Deploy from GitHub repo → select `finance-tracker-app`
  - Create two services: one tracking `staging`, one tracking `main`
  - Set env vars on each: `DATABASE_URL` (Neon connection string), `REDIS_URL`, `JWT_SECRET_KEY`, `FRONTEND_URL`
- [ ] **Neon** — Postgres project created, connection string in hand for Railway's `DATABASE_URL`

I can't do any of this for you — it's dashboard clicks and credentials I should never see. Ping me once it's done and I'll help verify the workflow picks it up correctly.

## Pre-Deploy (routine, every release from here on)

- [ ] All tests passing in CI — **not yet verified**: this exact workflow has never run in GitHub Actions. QA Lead's 23/23 passed locally in sandbox; first real signal comes from the first push once `TEST_SECRET_KEY` is set.
- [ ] Code reviewed and approved — done (PR #1 merged to `main`, Gatekeeper PASS at both Tech Lead and QA Lead stages)
- [ ] No known critical bugs in release — none open; one MEDIUM item carried forward (refresh_token duplicated in body + cookie, tracked, not blocking)
- [ ] Database migration tested — `alembic/versions/0001_create_users_table.py` is a fresh `CREATE TABLE`, no existing data to migrate. Low risk, but unverified against a real Neon instance (only tested against in-memory SQLite so far)
- [ ] Feature flags configured — none in use for this story
- [ ] Rollback plan documented — see below
- [ ] Deploy window: Mon–Thu, 10am–2pm (per blueprint's own policy)

## Deploy

- [ ] Push to `staging` first — verify Railway auto-deploys the API, watch Actions for the frontend job (expected to skip — no `apps/web` yet)
- [ ] Smoke test staging: `GET /health` and `POST /api/v1/auth/register` against the live Railway staging URL
- [ ] Soak on staging ≥24h before promoting (per blueprint's own pre-production gate)
- [ ] Merge/push to `main` → GitHub pauses at the `production` environment gate → you click Approve
- [ ] Confirm Railway's production service redeploys after approval

## Post-Deploy

- [ ] Confirm `/health` and `/health/ready` are green on production
- [ ] Update FINTRACK-13 Jira status, close the ticket
- [ ] Note the deployed commit SHA somewhere retrievable — this becomes `rollback_tag` for the *next* release

## Rollback Triggers

- Error rate > 1%
- p99 latency > 2s
- `/health` check failing
- **Action:** `git revert HEAD && git push origin main` — Railway redeploys the reverted commit automatically. Notify via Jira comment within 5 minutes.
