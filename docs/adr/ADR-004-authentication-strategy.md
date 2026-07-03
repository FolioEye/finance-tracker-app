# ADR-004: Authentication Strategy

**Status:** Accepted
**Date:** 2026-07-03
**Story:** FINTRACK-13 (User Registration), FINTRACK-14 (Login/Logout)
**Author:** Tech Lead Agent

## Context

PM's approved business case (FINTRACK-001 / Epic FINTRACK-12) set two architecture constraints relevant here:

1. "Identity is not Authentication" -- the User/Identity entity must be modeled separately from the Account/financial-profile entity from day one, free to do now, expensive to retrofit once P2 adds investor/advisor/household relationships.
2. Tech Lead should evaluate a managed auth provider (e.g. Supabase Auth) over hand-rolled JWT/session/MFA/OAuth logic, given Postgres is the chosen DB, to reduce engineering burden without adding infra that contradicts the minimise-operational-complexity MVP priority.

## Decision

**Hand-rolled JWT (python-jose) + bcrypt, not a managed auth provider, for the MVP.**

## Considered Options

### Option A: Supabase Auth (managed)
- Pros: less code to write and maintain; built-in MFA/OAuth/passwordless ready for P1; hosted.
- Cons: introduces a second managed dependency beyond what's already committed; Supabase's own `auth.users` table becomes the real source of identity truth living outside our migrations, which cuts directly against the "model Identity ourselves, separate from Account" constraint; harder to guarantee the strict Identity/Account separation PM required; vendor lock-in tension with the app's privacy-first positioning.

### Option B: Hand-rolled JWT + bcrypt (chosen)
- Pros: full control over the Identity entity and its separation from Account (our own `users` table, our own migration, our own domain model exactly as PM specified); no new managed dependency beyond Postgres/Redis already committed; JWT access (15min) + httpOnly refresh (7d) matches the constraint matrix directly; stays inside the same hexagonal architecture and test approach as the rest of the app.
- Cons: more code to write and maintain ourselves; MFA/OAuth/passwordless (P1) requires additional work a managed provider would give for free.

## Rationale

PM's note said "evaluate," not "adopt." Weighing a hard architectural requirement (Identity/Account separation) against a soft preference (less code), Option B wins for the MVP. The added P1 engineering cost is real but deferred, not blocking -- email/password auth alone satisfies every FINTRACK-13/FINTRACK-14 Gherkin scenario. Revisit this decision if/when OAuth (P1) work starts, since a managed provider's biggest practical win is federated login, not password auth.

## Consequences

- `users` table and all auth logic live in this repo, under our own Alembic migrations.
- Password hashing: bcrypt, cost factor 12, configurable via `BCRYPT_ROUNDS` env var.
- Tokens: JWT access (15 min, returned in response body) + refresh (7 days, httpOnly + Secure + SameSite=Strict cookie).
- `JWT_SECRET_KEY` must be injected via environment in every environment -- never committed, never defaulted in code.
- FINTRACK-14 (Login/Logout) reuses `TokenService` and `PasswordHasher` built for this story unchanged.
