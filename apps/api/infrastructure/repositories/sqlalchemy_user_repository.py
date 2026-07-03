"""SQLAlchemy adapter implementing the UserRepository port.

Every query goes through SQLAlchemy's parameterised query builder -- no
string-concatenated SQL exists anywhere in this file.
"""
from __future__ import annotations

import uuid
from typing import Optional

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from apps.api.domain.models.user import Email, User
from apps.api.domain.repositories.user_repository import (
    EmailAlreadyExistsError,
    UserRepository,
)
from apps.api.infrastructure.database.models import UserModel


def _to_domain(row: UserModel) -> User:
    return User(
        id=row.id,
        email=Email(row.email),
        password_hash=row.password_hash,
        email_verified=row.email_verified,
        is_active=row.is_active,
        created_at=row.created_at,
    )


class SqlAlchemyUserRepository(UserRepository):
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_email(self, email: Email) -> Optional[User]:
        stmt = select(UserModel).where(UserModel.email == str(email))
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def get_by_id(self, user_id: uuid.UUID) -> Optional[User]:
        stmt = select(UserModel).where(UserModel.id == user_id)
        result = await self._session.execute(stmt)
        row = result.scalar_one_or_none()
        return _to_domain(row) if row else None

    async def add(self, user: User) -> None:
        row = UserModel(
            id=user.id,
            email=str(user.email),
            password_hash=user.password_hash,
            email_verified=user.email_verified,
            is_active=user.is_active,
        )
        self._session.add(row)
        try:
            await self._session.flush()
        except IntegrityError as exc:
            # DB unique constraint is the final backstop against a race
            # between the get_by_email check and this insert.
            raise EmailAlreadyExistsError("An account with this email already exists") from exc
