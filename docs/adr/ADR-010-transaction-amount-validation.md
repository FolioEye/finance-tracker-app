# ADR-010: Transaction Amount Validation and Bearer-Token Authentication

**Status:** Accepted
**Date:** 2026-07-07
**Story:** FINTRACK-15 (Add Manual Transaction)
**Author:** Tech Lead Agent

## Context

FINTRACK-15 introduces two things this codebase hasn't needed before:

1. **An authenticated business-data endpoint.** `/register`, `/login`, and
   `/logout` all issue or invalidate tokens, but none of them require one
   to call. Adding transactions is the first endpoint that must verify
   *who* is calling, not just accept a request.
2. **Money.** Every prior story handled strings (email, password) or
   opaque tokens. Transaction amounts are the first place this codebase
   needs to represent currency and get arithmetic/precision right.

## Decision

**A) Bearer-token auth via `get_current_user_id`.** A FastAPI dependency
extracts `Authorization: Bearer <token>`, verifies it via the existing
`TokenService.decode()` (added for FINTRACK-14's logout), requires
`claims["type"] == "access"`, and trusts the `sub` claim as the user id
without a database round-trip. Consistent with the access-token trade-off
ADR-009 already accepted: a deactivated account's still-valid access token
remains usable for its own <=15-minute window. Revisit if a story ever
needs immediate hard revocation of access, not just refresh tokens.

**B) `Money` value object, `Decimal`-backed.** Amounts arrive as strings
(same rationale as `Email`/`LoginRequest.email` elsewhere in this
codebase: validation and user-facing messages live in the domain layer,
not the Pydantic boundary) and are parsed via `Decimal(raw)`, never
`float`. Validates: positive, at most 2 decimal places (checked via the
parsed `Decimal`'s exponent), and a hard ceiling of `999999999.99`
matching the Gherkin's exact rejected boundary value verbatim.

**C) SQL-injection-shaped input rejected at the domain layer for
free-text fields (category, note).** This is explicitly *not* the actual
SQL-injection defence -- SQLAlchemy's parameterised query builder (used
everywhere in this codebase, including the new
`SqlAlchemyTransactionRepository`) is what actually prevents injection,
regardless of what a string contains. The pattern-match reject exists
because FINTRACK-15's Gherkin explicitly requires a specific UX for this
case (a named validation error, a logged security event, confirmable
database integrity) that "the query was parameterised so it doesn't
matter" doesn't produce on its own. The pattern is deliberately narrow
(statement-terminator-or-comment-marker plus a destructive keyword) so it
doesn't reject legitimate text like "O'Brien's Cafe".

## Considered Options (amount validation)

- **`float`.** Rejected outright: binary floating point cannot represent
  most currency values exactly, which is a correctness bug waiting to
  happen the first time two amounts are summed (out of scope for this
  story, but budgets/dashboards later will do exactly that).
- **Pydantic `condecimal`/`Decimal` field type at the DTO layer.** Rejected
  for the same reason `LoginRequest.email` isn't `EmailStr`: it would
  reject malformed input with a generic 422 before the domain layer ever
  runs, instead of the specific 400 messages ("Amount must be a positive
  number", "Amount exceeds maximum allowed limit") the Gherkin requires.
- **`Decimal` parsed and validated in the domain layer (chosen).** Matches
  this codebase's existing split between shape validation (Pydantic) and
  business-rule validation (domain), and gives exact control over every
  rejection message the Gherkin specifies.

## Considered Options (authorization)

- **Trust a `user_id` field in the request body/query.** Rejected outright
  -- this is the textbook IDOR vulnerability the constraint matrix's
  zero-trust principle exists to prevent. Every transaction operation
  must derive the acting user from the verified JWT, never from anything
  the client can set directly.
- **Session lookup against Redis/DB on every request.** Rejected for this
  story's scope: adds a hop to every single authenticated request for a
  revocation guarantee this story doesn't need (deactivation-mid-session
  is already an accepted, documented trade-off from ADR-009). Revisit if
  a future story needs it.
- **Stateless JWT claim trust (chosen).** Consistent with the rest of this
  codebase's auth model; no new infrastructure dependency introduced.

## Consequences

- `get_current_user_id` becomes the auth dependency every future
  authenticated endpoint (FINTRACK-16 onward) should reuse, rather than
  each story inventing its own.
- AC4's "affects budget total" is **not implemented by this story** -- no
  Budget entity exists yet (that's FINTRACK-20). The transaction itself is
  fully persisted and listed; the budget-total assertion in the BA's
  Gherkin happy-path scenario can't be verified until FINTRACK-20 lands.
  QA Lead should test transaction-list presence for that scenario, not a
  budget figure, until then.
- AC5 ("Editable/deletable") is implemented (`PATCH`/`DELETE`) even though
  none of the BA's 4 Gherkin scenarios exercise it -- QA Lead has no
  Gherkin mapping for these two handlers and should add scenarios rather
  than leave them untested.
- A SQL-injection-shaped-input reject at the domain layer is
  defence-in-depth on top of (not instead of) parameterised queries. If
  this pattern is ever treated as *the* injection defence rather than a
  UX/compliance nicety, that would be a misunderstanding of this ADR to
  correct on sight.
