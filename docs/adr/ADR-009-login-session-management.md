# ADR-009: Login Rate Limiting and Session Invalidation

**Status:** Accepted
**Date:** 2026-07-07
**Story:** FINTRACK-14 (Login/Logout)
**Author:** Tech Lead Agent

## Context

FINTRACK-14 reuses `TokenService` and `BcryptPasswordHasher` from FINTRACK-13
unchanged, per ADR-004. Two things it does NOT reuse as-is:

1. **Rate limiting.** FINTRACK-13's `/register` endpoint rate-limits via
   `slowapi`, keyed on IP only (`get_remote_address`). FINTRACK-14's AC4
   requires **5 attempts / 15 min per account+IP** — a compound key.
   `slowapi`'s decorator keys off request metadata available before the
   body is parsed; it has no clean way to combine IP with a field out of
   the JSON body. Reusing it as-is would only give IP-based limiting, which
   both under- and over-blocks: a shared office IP could lock out every
   user, and a distributed attempt against one account from many IPs
   wouldn't be caught at all.
2. **Logout / session invalidation.** JWTs are stateless by design — there
   is no server-side session record to delete. "Logout invalidates the
   current session token" (AC5) needs an explicit mechanism, since a
   bare JWT stays valid until its own `exp` regardless of what the client
   does with it.

## Decision

**A) Rate limiting:** a small `RateLimiter` port (hexagonal, same pattern as
`PasswordHasher`) with a `RedisRateLimiter` adapter, keyed on
`login:{email}:{ip}`, fixed-window counter via Redis `INCR` + `EXPIRE`.
Checked *before* any database access, so a rate-limited attempt never
reaches the DB (Gherkin scenario 3).

**B) Session invalidation:** a `TokenRevocationStore` port with a
`RedisTokenRevocationStore` adapter — a denylist keyed on the refresh
token's `jti`, set with a TTL equal to the token's own remaining lifetime
(so the denylist entry never outlives the token it's blocking, and never
needs manual cleanup). Logout decodes the refresh token cookie, extracts
`jti` + `exp`, and adds it to the denylist.

## Considered Options (rate limiting)

- **Reuse slowapi with a custom `key_func`.** Rejected: `key_func` runs
  before FastAPI has parsed/validated the request body, so it can't read
  `payload.email` without re-parsing the raw body manually — fragile and
  duplicates work Pydantic already does.
- **In-memory counter (dict + TTL).** Rejected: doesn't survive multiple
  worker processes/replicas, and Redis is already a committed dependency
  (constraint matrix: "Redis for sessions and hot reference data").
- **Redis fixed-window counter (chosen).** Matches the existing
  infrastructure commitment, is simple to reason about, and the small
  race between `INCR` and `EXPIRE` on the very first request in a window
  is an accepted, standard trade-off for this class of limiter (worst
  case: one extra request let through on key creation, not a security
  bypass).

## Considered Options (logout)

- **Short-lived access tokens only, no revocation at all.** Rejected:
  doesn't satisfy AC5 ("logout invalidates the current session token") —
  a stolen refresh token would remain valid for up to 7 days after the
  user logs out.
- **Stateful sessions (session ID in DB/Redis, JWT replaced entirely).**
  Rejected for this story: a bigger architectural change than a 2-point
  story warrants, and abandons the JWT approach ADR-004 already committed
  to for the whole app, not just this endpoint.
- **Redis denylist of the refresh token's `jti`, TTL'd to remaining
  lifetime (chosen).** Minimal change on top of the existing JWT design;
  `jti` was already present on the refresh token specifically so a future
  revocation list could be added (see `token_service.py` comment from
  FINTRACK-13).

## Consequences

- The **access token is not revoked on logout** and remains valid for up
  to its own 15-minute expiry after the user logs out. This is a known,
  accepted trade-off given the story's scope (2 points) — the window is
  short, and full access-token revocation would require checking the
  denylist on every authenticated request rather than only at logout/
  refresh time. Revisit if a future story needs "log out everywhere" or
  immediate hard revocation (both already out of scope per FINTRACK-14's
  Gherkin header).
- Login and register now use two different rate-limiting mechanisms
  (`slowapi` for register, the new Redis `RateLimiter` port for login).
  This is a deliberate divergence, not drift — worth revisiting if a
  third endpoint needs compound-key limiting, at which point migrating
  register onto the same `RateLimiter` port would remove the duplication.
- Requires Redis to be reachable for `/login` and `/logout` to function
  (previously only used by `slowapi`'s in-memory default storage, so this
  is the first *hard* runtime dependency on Redis connectivity). CI's
  `redis:7` service container already covers this for tests.
