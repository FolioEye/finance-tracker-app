"""bcrypt password hashing adapter. Never logs, stores, or echoes plaintext."""
from __future__ import annotations

from abc import ABC, abstractmethod
from functools import lru_cache

import bcrypt


class PasswordHasher(ABC):
    @abstractmethod
    def hash(self, raw_password: str) -> str:
        ...

    @abstractmethod
    def verify(self, raw_password: str, password_hash: str) -> bool:
        ...


class BcryptPasswordHasher(PasswordHasher):
    def __init__(self, rounds: int = 12) -> None:
        self._rounds = rounds

    def hash(self, raw_password: str) -> str:
        salt = bcrypt.gensalt(rounds=self._rounds)
        return bcrypt.hashpw(raw_password.encode("utf-8"), salt).decode("utf-8")

    def verify(self, raw_password: str, password_hash: str) -> bool:
        try:
            return bcrypt.checkpw(raw_password.encode("utf-8"), password_hash.encode("utf-8"))
        except ValueError:
            # Malformed hash -- treat as verification failure, not a crash.
            return False


@lru_cache(maxsize=1)
def dummy_hash_for_timing_safety() -> str:
    """A bcrypt hash of a fixed placeholder password, computed once per
    process (bcrypt hashing is deliberately expensive, so this must not be
    recomputed per request).

    Used by FINTRACK-14's login flow: when no user exists for the given
    email, verifying the supplied password against this dummy hash keeps
    the response time consistent with a real (wrong-password) failure --
    without it, an attacker could enumerate valid emails by measuring
    whether a login attempt returns instantly (no such user, no bcrypt
    call) or after bcrypt's verify cost (real user, wrong password).
    """
    from apps.api.config import get_settings

    settings = get_settings()
    return BcryptPasswordHasher(rounds=settings.bcrypt_rounds).hash(
        "fintrack-timing-mitigation-placeholder-9f3a2"
    )
