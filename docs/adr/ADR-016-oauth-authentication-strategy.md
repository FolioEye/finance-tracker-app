# ADR-016: OAuth Authentication Strategy (Google + Apple)

## Status
Accepted, 2026-08-03. Story: FINTRACK-38 / FINTRACK-42 / FINTRACK-43.

## Context
ADR-004 (2026-07-03) chose a hand-rolled JWT (PyJWT) + bcrypt authentication
system over a managed provider (specifically rejecting Supabase Auth)
because a managed provider's built-in user table would have broken the
required Identity/Account entity separation ("Identity is not
Authentication" -- see `apps/api/domain/models/user.py`'s module
docstring). ADR-004 explicitly flagged itself for revisit once OAuth (P1)
work started, since a managed provider's single biggest practical
advantage is federated login -- exactly what this story needs.

This story is FinTrack's first release with a frontend at all
(`apps/web` did not exist before FINTRACK-41), and ships OAuth login via
Google and Apple as that frontend's first feature, since App Store
Guideline 4.8 requires Apple Sign-In alongside any other third-party
login option offered.

## Decision
**Keep the existing hand-rolled JWT/bcrypt system. Do not adopt a managed
auth provider for OAuth.**

Both Google and Apple's "Sign in with" flows hand the frontend a signed
ID token (a JWT) after the user authenticates with the provider directly
-- verifying that token's signature against the provider's own published
public keys (Google's via `google-auth`, Apple's via its JWKS endpoint +
PyJWT) requires no server-side authorization-code exchange, no client
secret, and critically, no managed identity provider. This is genuinely
just JWT signature verification against a third party's public key, the
same shape of problem the existing `TokenService` already solves for
FinTrack's own tokens.

Concretely: `apps/api/infrastructure/security/oauth_verifier.py` verifies
the provider's ID token and returns a normalised `OAuthIdentity`
(provider, subject, email, email_verified). `oauth_login_user.py` then
finds-or-links-or-creates a `User` row and issues FinTrack's own
access/refresh JWT pair via the existing, unchanged `TokenService` --
identical token shape, identical cookie policy, identical
`get_current_user_id` dependency every other authenticated endpoint
already uses.

## Alternatives Considered

**Migrate to Supabase Auth (or Auth0/Clerk) for OAuth specifically,
password auth staying as-is.** Rejected: running two parallel auth
systems (one for password users, a different one for OAuth users) is
strictly more complexity than one system handling both, not less --
session/token issuance, the `users` table, and every authenticated
route's identity check would all need to branch on which system a given
user belongs to.

**Migrate everything (password + OAuth) to a managed provider.**
Rejected for the same reason ADR-004 rejected it originally: a managed
provider's own user table is the provider's, not this app's -- it does
not sit cleanly behind the `UserRepository` port the rest of this
codebase is built around, and re-doing that separation work now, mid P1,
for a benefit (federated login) that's achievable without it, is not
justified.

## Consequences
- `users.password_hash` becomes nullable -- an OAuth-only user has no
  password at all, not a placeholder hash (migration 0011).
- New `users.oauth_provider` / `users.oauth_subject` columns, unique
  together, are the stable identity key for a returning OAuth user (an
  email alone isn't stable enough -- a user can change their email with
  the provider).
- Account linking (an OAuth login matching an existing password
  account's email) is gated on the provider's own `email_verified` claim
  -- the single most important security control this story adds. See
  `oauth_login_user.py`'s `OAuthLoginUserHandler.handle` for the full
  reasoning.
- `LoginUserHandler` (password login) is unchanged, but now must
  correctly reject a password-login attempt against a `password_hash IS
  NULL` (OAuth-only) row with the same generic invalid-credentials error
  as any other failure -- verified in
  `tests/unit/test_oauth_login_user.py` and should be re-verified against
  the real `LoginUserHandler` at QA Lead's pass.
- No new secret needs to be provisioned for *verifying* Google/Apple ID
  tokens -- both providers' public keys are fetched from their own
  well-known endpoints. `GOOGLE_OAUTH_CLIENT_ID` and
  `APPLE_OAUTH_CLIENT_IDS` are audience values, not secrets, and can be
  set as plain (non-secret) environment variables.
