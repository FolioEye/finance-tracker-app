"""User (Identity) domain entity.

Deliberately separate from any future Account/financial-profile entity per
PM architecture constraint: "Identity is not Authentication" -- this entity
models *who the person is*, not their financial data. A future Account
entity will reference user_id as a foreign key, never the other way around.
See docs/adr/ADR-004-authentication-strategy.md and, for OAuth specifically,
docs/adr/ADR-016-oauth-authentication-strategy.md.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional


class InvalidEmailError(ValueError):
    """Raised when an email fails format validation."""


class WeakPasswordError(ValueError):
    """Raised when a password fails the minimum strength policy."""


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# FINTRACK-42/43 (ADR-016): the two OAuth providers this app supports.
# Kept as a plain tuple of strings rather than a full enum -- the value is
# only ever compared for equality or persisted as a plain column, never
# branched on with provider-specific business logic at the domain layer
# (that branching lives in infrastructure/security/oauth_verifier.py,
# where each provider already needs its own verification code anyway).
OAUTH_PROVIDERS = ("google", "apple")


@dataclass(frozen=True)
class Email:
    """Value object -- validated, normalised email address.

    Rejects malformed input (including SQL-injection-style strings, which
    never match the format regex) before it reaches any repository or query.
    """

    value: str

    def __post_init__(self) -> None:
        normalised = self.value.strip().lower()
        if not _EMAIL_RE.match(normalised):
            raise InvalidEmailError("Invalid email format")
        object.__setattr__(self, "value", normalised)

    def __str__(self) -> str:
        return self.value


def validate_password_strength(raw_password: str, min_length: int = 10) -> None:
    """Minimum strength policy: length + at least one letter and one digit.

    Raises WeakPasswordError with a message safe to show the user. Never
    logs or echoes the raw password itself.
    """
    if len(raw_password) < min_length:
        raise WeakPasswordError(
            f"Password does not meet minimum strength requirements (at least {min_length} characters)"
        )
    if not re.search(r"[A-Za-z]", raw_password) or not re.search(r"\d", raw_password):
        raise WeakPasswordError(
            "Password does not meet minimum strength requirements (letters and numbers required)"
        )


@dataclass
class User:
    """The Identity entity. Holds no financial data by design.

    password_hash is Optional as of FINTRACK-42/43 (ADR-016): an
    OAuth-only user (one who has only ever signed in via Google or Apple)
    has no password at all, rather than a dummy/placeholder hash. Callers
    that authenticate by password (LoginUserHandler) must treat a `None`
    password_hash as an automatic rejection -- see that handler's own
    dummy-hash-timing-safety path, which already covers this case because
    `PasswordHasher.verify` is never called with a `None` hash in the
    first place (the "no such active user" branch runs first for an
    inactive/missing account; a `None` password_hash on an active row
    would otherwise reach `verify()` -- callers must guard this explicitly
    if that case is ever reachable, since bcrypt's `verify` requires a
    real hash string).
    """

    id: uuid.UUID
    email: Email
    password_hash: Optional[str]  # bcrypt hash, or None for an OAuth-only user
    email_verified: bool = False
    is_active: bool = True
    oauth_provider: Optional[str] = None  # "google" | "apple" | None
    oauth_subject: Optional[str] = None  # provider's stable user id ("sub" claim)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def new(email: Email, password_hash: str) -> "User":
        return User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            email_verified=False,
            is_active=True,
            oauth_provider=None,
            oauth_subject=None,
            created_at=datetime.now(timezone.utc),
        )

    @staticmethod
    def new_oauth(email: Email, provider: str, subject: str, email_verified: bool) -> "User":
        """FINTRACK-42/43: constructs a brand-new OAuth-only user -- no
        password_hash at all. `email_verified` is trusted from the
        provider's own verified ID token claim (see oauth_verifier.py),
        never assumed true by default.
        """
        if provider not in OAUTH_PROVIDERS:
            raise ValueError(f"Unsupported OAuth provider: {provider}")
        return User(
            id=uuid.uuid4(),
            email=email,
            password_hash=None,
            email_verified=email_verified,
            is_active=True,
            oauth_provider=provider,
            oauth_subject=subject,
            created_at=datetime.now(timezone.utc),
        )
