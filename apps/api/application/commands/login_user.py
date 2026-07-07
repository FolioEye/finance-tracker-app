"""LoginUserCommand + handler -- the use case for FINTRACK-14 (Login).

See docs/adr/ADR-009-login-session-management.md for the rate-limiting
and no-user-enumeration design decisions this handler implements.
"""
from __future__ import annotations

from dataclasses import dataclass

from apps.api.domain.models.user import Email, InvalidEmailError, User
from apps.api.domain.repositories.user_repository import UserRepository
from apps.api.infrastructure.security.password_hasher import (
    PasswordHasher,
    dummy_hash_for_timing_safety,
)
from apps.api.infrastructure.security.rate_limiter import RateLimitExceededError, RateLimiter
from apps.api.infrastructure.security.token_service import TokenPair, TokenService


class InvalidCredentialsError(Exception):
    """Raised on any login failure -- deliberately generic. Never reveals
    whether the failure was an unknown email, a malformed/SQLi-shaped
    email, a deactivated account, or a wrong password (no user
    enumeration, FINTRACK-14 AC2)."""


@dataclass(frozen=True)
class LoginUserCommand:
    email: str
    password: str
    client_ip: str


@dataclass(frozen=True)
class LoginUserResult:
    user: User
    tokens: TokenPair


class LoginUserHandler:
    """Depends only on ports (UserRepository, PasswordHasher, TokenService,
    RateLimiter) per hexagonal architecture -- no direct infrastructure
    imports beyond the port interfaces and the module-level dummy-hash
    helper (which itself only touches the PasswordHasher port).
    """

    def __init__(
        self,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        rate_limiter: RateLimiter,
        max_attempts: int = 5,
        window_seconds: int = 900,
    ) -> None:
        self._users = user_repository
        self._hasher = password_hasher
        self._tokens = token_service
        self._rate_limiter = rate_limiter
        self._max_attempts = max_attempts
        self._window_seconds = window_seconds

    async def handle(self, command: LoginUserCommand) -> LoginUserResult:
        # Rate limit is keyed on email+IP and checked BEFORE any DB call --
        # Gherkin scenario 3 requires a rate-limited attempt to never reach
        # the database. The raw (unvalidated) email is fine to use as part
        # of the rate-limit key here: it's only ever used as a Redis key
        # component, never interpolated into a query, logged verbatim, or
        # echoed back to the caller.
        rate_limit_key = f"login:{command.email.strip().lower()}:{command.client_ip}"
        allowed = await self._rate_limiter.check_and_increment(
            key=rate_limit_key,
            max_attempts=self._max_attempts,
            window_seconds=self._window_seconds,
        )
        if not allowed:
            raise RateLimitExceededError("Too many attempts, try again later")

        # Email format errors (including SQLi-shaped strings) are folded
        # into the same generic InvalidCredentialsError as "wrong password"
        # or "unknown email". Unlike registration, login must not leak
        # format-validity as a distinguishable signal -- FINTRACK-14's
        # Gherkin SQLi scenario expects the *generic* invalid-credentials
        # error, not a format-specific one.
        try:
            email = Email(command.email)
        except InvalidEmailError:
            self._hasher.verify(command.password, dummy_hash_for_timing_safety())
            raise InvalidCredentialsError("Invalid email or password")

        user = await self._users.get_by_email(email)
        if user is None or not user.is_active:
            # No such user (or deactivated) -- still run a bcrypt verify
            # against a dummy hash so this path takes about as long as a
            # real wrong-password rejection. Without this, response timing
            # alone would reveal whether the email is registered.
            self._hasher.verify(command.password, dummy_hash_for_timing_safety())
            raise InvalidCredentialsError("Invalid email or password")

        if not self._hasher.verify(command.password, user.password_hash):
            raise InvalidCredentialsError("Invalid email or password")

        tokens = self._tokens.issue_pair(user.id)
        return LoginUserResult(user=user, tokens=tokens)
