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
    async def add(self, user: User) -> None:
        """Persist a new user. Must raise EmailAlreadyExistsError on unique
        constraint violation rather than letting a raw DB exception escape."""
        ...
