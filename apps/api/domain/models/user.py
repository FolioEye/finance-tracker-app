"""User (Identity) domain entity.

Deliberately separate from any future Account/financial-profile entity per
PM architecture constraint: "Identity is not Authentication" -- this entity
models *who the person is*, not their financial data. A future Account
entity will reference user_id as a foreign key, never the other way around.
See docs/adr/ADR-004-authentication-strategy.md.
"""
from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


class InvalidEmailError(ValueError):
    """Raised when an email fails format validation."""


class WeakPasswordError(ValueError):
    """Raised when a password fails the minimum strength policy."""


_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


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
    """The Identity entity. Holds no financial data by design."""

    id: uuid.UUID
    email: Email
    password_hash: str  # bcrypt hash only -- never the raw password
    email_verified: bool = False
    is_active: bool = True
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    @staticmethod
    def new(email: Email, password_hash: str) -> "User":
        return User(
            id=uuid.uuid4(),
            email=email,
            password_hash=password_hash,
            email_verified=False,
            is_active=True,
            created_at=datetime.now(timezone.utc),
        )
