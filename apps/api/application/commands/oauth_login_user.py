"""OAuthLoginUserCommand + handler -- FINTRACK-42 (Google) / FINTRACK-43 (Apple).

Verifies the provider's ID token, then either logs in an existing
OAuth-linked user, links a verified-email match to an existing
password-based account, or creates a brand-new OAuth-only user -- then
issues the same JWT access/refresh pair every other login path issues.
See docs/adr/ADR-016-oauth-authentication-strategy.md.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.api.domain.models.user import Email, InvalidEmailError, User
from apps.api.domain.repositories.user_repository import EmailAlreadyExistsError, UserRepository
from apps.api.infrastructure.security.oauth_verifier import (
    AppleIdTokenVerifier,
    GoogleIdTokenVerifier,
    OAuthIdentity,
    OAuthProviderUnavailableError,
    OAuthTokenInvalidError,
)
from apps.api.infrastructure.security.rate_limiter import RateLimitExceededError, RateLimiter
from apps.api.infrastructure.security.token_service import TokenPair, TokenService


class OAuthLoginError(Exception):
    """Raised for any OAuth login failure the caller should treat as a
    generic 401 -- an invalid/unverifiable token or an email-verification
    gate failure. Deliberately does not distinguish these to the client,
    same no-enumeration principle as InvalidCredentialsError.

    OAuthProviderUnavailableError is deliberately NOT wrapped into this --
    it propagates as-is so the API layer can return 503 for a transient
    provider outage instead of 401 for a genuinely invalid token.
    """


@dataclass(frozen=True)
class OAuthLoginCommand:
    provider: str  # "google" | "apple"
    id_token: str
    client_ip: str


@dataclass(frozen=True)
class OAuthLoginResult:
    user: User
    tokens: TokenPair
    is_new_user: bool


class OAuthLoginUserHandler:
    """Depends only on ports (UserRepository, TokenService, RateLimiter)
    plus the two provider verifiers -- no direct infrastructure imports
    beyond those, per hexagonal architecture.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        token_service: TokenService,
        rate_limiter: RateLimiter,
        google_verifier: GoogleIdTokenVerifier,
        apple_verifier: AppleIdTokenVerifier,
        max_attempts: int = 5,
        window_seconds: int = 900,
    ) -> None:
        self._users = user_repository
        self._tokens = token_service
        self._rate_limiter = rate_limiter
        self._google_verifier = google_verifier
        self._apple_verifier = apple_verifier
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds

    async def handle(self, command: OAuthLoginCommand) -> OAuthLoginResult:
        # Same rate-limit-before-any-work discipline as LoginUserHandler,
        # keyed on provider+IP since there's no email to key on until
        # after the token is verified.
        rate_limit_key = f"oauth_login:{command.provider}:{command.client_ip}"
        allowed = await self._rate_limiter.check_and_increment(
            key=rate_limit_key,
            max_attempts=self._max_attempts,
            window_seconds=self._window_seconds,
        )
        if not allowed:
            raise RateLimitExceededError("Too many attempts, try again later")

        identity = await self._verify(command.provider, command.id_token)

        # 1. Returning OAuth user -- looked up by (provider, subject), the
        # stable identity, not by email (an email can change with the
        # provider; the subject id cannot).
        existing = await self._users.get_by_oauth_identity(identity.provider, identity.subject)
        if existing is not None:
            tokens = self._tokens.issue_pair(existing.id)
            return OAuthLoginResult(user=existing, tokens=tokens, is_new_user=False)

        # Provider's email must itself be well-formed -- defence in depth,
        # even though both providers are expected to only ever hand back
        # valid addresses.
        try:
            email = Email(identity.email)
        except InvalidEmailError as exc:
            raise OAuthLoginError("OAuth provider returned an invalid email") from exc

        # 2. Account-linking match by email -- gated on the provider's own
        # email_verified claim. Linking an OAuth identity onto an existing
        # password account based on an *unverified* email would let
        # anyone who merely typed in someone else's address at the OAuth
        # provider take over that person's FinTrack account -- the single
        # most important security check in this whole flow.
        by_email = await self._users.get_by_email(email)
        if by_email is not None:
            if not identity.email_verified:
                raise OAuthLoginError(
                    "Cannot link this OAuth account: email is not verified with the provider"
                )
            await self._users.link_oauth_identity(by_email.id, identity.provider, identity.subject)
            linked_user = User(
                id=by_email.id,
                email=by_email.email,
                password_hash=by_email.password_hash,
                email_verified=by_email.email_verified,
                is_active=by_email.is_active,
                oauth_provider=identity.provider,
                oauth_subject=identity.subject,
                created_at=by_email.created_at,
            )
            tokens = self._tokens.issue_pair(by_email.id)
            return OAuthLoginResult(user=linked_user, tokens=tokens, is_new_user=False)

        # 3. Brand-new OAuth-only user.
        new_user = User.new_oauth(
            email=email,
            provider=identity.provider,
            subject=identity.subject,
            email_verified=identity.email_verified,
        )
        try:
            await self._users.add(new_user)
        except EmailAlreadyExistsError as exc:
            # Race: another request created this email between the
            # get_by_email check above and this insert. Treat the same as
            # any other login failure rather than a 500 -- a client retry
            # will hit the get_by_oauth_identity/by_email branches above
            # and succeed.
            raise OAuthLoginError("Account already exists, please try again") from exc

        tokens = self._tokens.issue_pair(new_user.id)
        return OAuthLoginResult(user=new_user, tokens=tokens, is_new_user=True)

    async def _verify(self, provider: str, id_token: str) -> OAuthIdentity:
        if provider == "google":
            verify_call = self._google_verifier.verify
        elif provider == "apple":
            verify_call = self._apple_verifier.verify
        else:
            raise OAuthLoginError(f"Unsupported OAuth provider: {provider}")

        try:
            return await verify_call(id_token)
        except OAuthTokenInvalidError as exc:
            raise OAuthLoginError("Invalid OAuth token") from exc
        # OAuthProviderUnavailableError propagates as-is -- see the class
        # docstring above.
