"""Port (interface) for user persistence. Infrastructure provides the adapter."""
from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from typing import Optional

from apps.api.domain.models.user import Email, User


class EmailAlreadyExistsError(Exception):
    """Raised when attempting to register an email that is already taken."""


class UserRepository(ABC):
    @abstractmethod
    async def get_by_email(self, email: Email) -> Optional[User]:
        ...

    @abstractmethod
    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        ...

    @abstractmethod
    async def get_by_oauth_identity(self, provider: str, subject: str) -> Optional[User]:
        """FINTRACK-42/43: looks a user up by their OAuth identity
        (provider + provider's stable subject id), independent of email --
        this is the primary lookup for a returning OAuth user, since an
        email alone can't be trusted as a long-term stable key (a user
        can change their email with the provider) and doesn't
        disambiguate two different providers claiming the same address."""
        ...

    @abstractmethod
    async def add(self, user: User) -> None:
        """Persist a new user. Must raise EmailAlreadyExistsError on unique
        constraint violation rather than letting a raw DB exception escape."""
        ...

    @abstractmethod
    async def link_oauth_identity(self, user_id: uuid.UUID, provider: str, subject: str) -> None:
        """FINTRACK-42/43: attaches an OAuth identity to an existing
        (password-based) account, found by verified email match. Kept as
        its own method rather than a generic `update()` -- this is the
        one specific, narrow mutation OAuthLoginUserHandler needs, and a
        broad update() would invite scope creep at the port level."""
        ...
