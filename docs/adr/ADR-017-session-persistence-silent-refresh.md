# ADR-017: Session persistence via silent token refresh

**Status:** Accepted
**Date:** 2026-09-10
**Story:** FINTRACK-60 (EP-01 Authentication) — ACs FINTRACK-60-AC1..AC6
**Rigor tier:** Mid-market (raised from SME at this story's Step 1; `tier_authority` = Mr M)
**Supersedes nothing. Extends:** ADR-004 (authentication strategy), ADR-009 (login session management), ADR-016 (OAuth authentication strategy)

## Context

The access JWT is memory-only with a 15-minute lifetime, per the constraint matrix. `/register`, `/login` and `/oauth/*` all already mint a 7-day `refresh_token` and set it as an httpOnly, Secure, SameSite=Strict cookie scoped to `path=/api/v1/auth`.

Nothing ever reads that cookie back. There is no `POST /api/v1/auth/refresh`, and `apps/web` performs no silent-refresh call on app load — `ProtectedRoute` reads `accessToken` straight from the zustand store, finds `null` after any page reload, and redirects to `/login`. Every page refresh, reopened tab, or restarted browser therefore drops a returning user at the Google sign-in screen while a valid refresh cookie exists.

### The deeper cause found during this design pass

The PM business case framed this as "the cookie is minted but never read back." Reading the deployed topology shows a second, prior fault:

- `apps/web` is served from Hostinger at `myfintrack.gtech45.com`
- The API runs on Railway at `finance-tracker-app-production-cfaf.up.railway.app`

Those are different registrable domains, so every browser→API call is **cross-site**, not merely cross-origin. A `SameSite=Strict` cookie is not sent on cross-site requests, and is not stored from a cross-site response. The refresh cookie has therefore most likely never existed in a real user's browser. Adding a refresh endpoint alone would have shipped a feature that could not work, and the symptom would have been indistinguishable from the bug we set out to fix.

This is the third defect traceable to the same split. CORS middleware was found entirely absent for the same reason during FINTRACK-38's Release Pro pass (2026-08-09).

## Decision

### 1. Make the frontend and API same-site (infrastructure)

Attach the custom domain **`api.gtech45.com`** to the Railway `finance-tracker-app` service (port 8000) and point `apps/web` at it via `VITE_API_BASE_URL`.

`myfintrack.gtech45.com` and `api.gtech45.com` share the registrable domain `gtech45.com`, so requests between them are same-site. `SameSite=Strict` is then honoured and **no cookie attribute changes** — the strictest CSRF posture is retained.

**Rejected: `SameSite=None`.** It is a pure code change and would have shipped inside this story with no DNS step. It was rejected because it spends security posture to save an infrastructure step: it removes the SameSite CSRF defence from the entire auth path, and would have required a compensating CSRF token on the rotation endpoint to stay defensible at Mid-market — more net code than the DNS record it avoids. `SameSite=Lax` was also rejected: it permits the cookie on top-level cross-site *navigations* only, not on the `fetch()` this feature depends on, so it does not solve the problem at all.

CORS is unaffected — same-site is not same-origin, so `CORSMiddleware` is still required. It is already configured with `allow_credentials=True` and `CORS_ALLOWED_ORIGINS` already contains `https://myfintrack.gtech45.com`.

### 2. `POST /api/v1/auth/refresh` with strict rotation (backend)

A new endpoint reads the httpOnly cookie, validates it, **rotates** it, and returns a fresh access token.

Sequence, fail-closed at each step:

1. Read `refresh_token` from `request.cookies`; absent → 401.
2. `TokenService.decode()` — signature and expiry verified; expired or malformed → 401.
3. Reject unless `claims["type"] == "refresh"` — an access token presented here must not work.
4. `revocation_store.is_revoked(jti)` → revoked → 401. **This is the replay check (AC5), and it is the first code in the system to read `is_revoked()`** — until now only `/logout` wrote to that store and nothing consulted it.
5. `revocation_store.revoke(old_jti, exp)` — the presented token is burned *before* the new pair is issued, so a crash between the two fails closed (user re-authenticates) rather than open (two live refresh tokens).
6. `TokenService.issue_pair(user_id)` → new access token + new refresh token, each with a fresh `jti`.
7. Set the new refresh cookie with attributes identical to `/login`, `/register` and `/oauth/*`.

No new tables, no new infrastructure. `jti` already exists on both token types and `RedisTokenRevocationStore` already expires denylist entries at each token's natural expiry, so the store stays bounded by construction.

**Layering** follows the existing hexagonal split exactly: `RefreshSessionCommand`/`RefreshSessionHandler` in `application/commands/`, mirroring `LogoutUserHandler`; the route in `presentation/api/v1/auth.py`; wiring in `dependencies.py` via a per-request factory. No new repository — token validity is derived from the signed token plus the denylist, not from user state, so the handler needs no DB session.

**The refresh token is never in the response body**, matching the F-02 policy already documented on `RegisterResponse`/`LoginResponse`. Cookie only.

**Rate limited** at the same 5-per-15-minute budget as login, keyed by IP. An unauthenticated endpoint that performs a Redis write and a JWT sign is worth bounding.

### 3. Silent refresh before route evaluation (frontend)

`authStore` gains a `bootstrapState: "pending" | "done"`. `ProtectedRoute` renders a spinner while `pending` and only evaluates `accessToken` once `done`, so it cannot redirect before the refresh attempt resolves (AC2). Because React Router preserves the requested location, a successful refresh lands the user on the route they asked for with query params intact (AC3) — no redirect to `/login` and back, and therefore no `/login` flash.

The refresh call is a **single shared in-flight promise** at module scope. This is the deliberate answer to strict rotation's one sharp edge: two tabs waking simultaneously would otherwise both present the same cookie, and the second would be correctly rejected as a replay. Sharing one promise per document collapses that to a single rotation. Across *separate* tabs it can still occur; see Consequences.

## Consequences

**Positive**

- Registration, login and OAuth session persistence are all repaired by the same domain change, not just the new endpoint.
- Strict rotation makes a stolen refresh token single-use, and its reuse is both rejected and logged — a real detection signal we did not previously have.
- `SameSite=Strict` is retained; no CSRF token is needed on the rotation endpoint.
- No schema change, no new service, no new dependency.

**Negative / accepted risks**

- **Cross-tab rotation race.** Two browser tabs restored simultaneously can each present the same refresh cookie; the loser gets a 401 and is sent to `/login`. Accepted rather than mitigated with a grace window, because a replay-tolerant window is precisely what defeats rotation as a theft detector. Revisit with a `BroadcastChannel` lock if it proves common in practice.
- **Redis becomes a hard auth dependency.** If Redis is unavailable, `is_revoked()` fails and refresh fails closed — users are logged out rather than admitted unchecked. Correct direction, but it raises Redis from convenience to availability-critical for sessions.
- **A DNS/certificate step now sits on the critical path** for this story, which a `SameSite=None` change would not have. Deliberate, per the rejection above.
- The Railway `*.up.railway.app` domain keeps working, so a frontend build still pointing at it will silently keep the broken cross-site behaviour. The cutover is only complete once `VITE_API_BASE_URL` is rebuilt.

## Verification

The decisive test is not that `/refresh` returns 200 — it is that the cookie **exists in the browser at all** after the domain change. That is checkable before the endpoint ships: log in on the deployed frontend and confirm a `refresh_token` cookie is present for `api.gtech45.com` in DevTools. If it is absent, the same-site fix has not landed and no amount of endpoint correctness will help.

## Data classification (Mid-market requirement)

| Field | Class | Handling |
|---|---|---|
| `refresh_token` (cookie value) | Credential | Never logged, never in a response body, httpOnly so unreadable by script |
| `access_token` (response body) | Credential | Never logged; memory-only on the client |
| `jti` (both tokens) | Internal | Safe to log; opaque UUID, not user-identifying |
| `sub` / `user_id` | PII (pseudonymous) | Logged as `user_id` only, consistent with existing auth logging |
| Email | PII | Not touched by this endpoint — deliberately absent from the refresh path |

Structured log events added: `refresh_attempt`, `refresh_succeeded` (`user_id`), `refresh_failed` (no reason detail, matching login's no-enumeration discipline), `refresh_replay_detected` (`jti`, WARNING — this one is a security signal and should feed FINTRACK-64's alerting).
