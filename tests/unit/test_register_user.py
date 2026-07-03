"""Unit tests for RegisterUserHandler. External deps mocked per constraint matrix."""
from __future__ import annotations

import uuid

import pytest

from apps.api.application.commands.register_user import (
    PasswordMismatchError,
    RegisterUserCommand,
    RegisterUserHandler,
)
from apps.api.domain.models.user import Email, InvalidEmailError, User, WeakPasswordError
from apps.api.domain.repositories.user_repository import EmailAlreadyExistsError
from apps.api.infrastructure.security.token_service import TokenPair


class FakeUserRepository:
    def __init__(self) -> None:
        self.users: dict[str, User] = {}
        self.added: list[User] = []

    async def get_by_email(self, email: Email):
        return self.users.get(str(email))

    async def get_by_id(self, user_id: uuid.UUID):
        return next((u for u in self.users.values() if u.id == user_id), None)

    async def add(self, user: User) -> None:
        if str(user.email) in self.users:
            raise EmailAlreadyExistsError("An account with this email already exists")
        self.users[str(user.email)] = user
        self.added.append(user)


class FakePasswordHasher:
    def hash(self, raw_password: str) -> str:
        return f"hashed:{raw_password}"

    def verify(self, raw_password: str, password_hash: str) -> bool:
        return password_hash == f"hashed:{raw_password}"


class FakeTokenService:
    def issue_pair(self, user_id: uuid.UUID) -> TokenPair:
        return TokenPair(
            access_token="fake-access",
            refresh_token="fake-refresh",
            access_token_expires_in_seconds=900,
        )


@pytest.fixture
def handler() -> RegisterUserHandler:
    return RegisterUserHandler(
        user_repository=FakeUserRepository(),
        password_hasher=FakePasswordHasher(),
        token_service=FakeTokenService(),
        min_password_length=10,
    )


@pytest.mark.asyncio
async def test_successful_registration(handler: RegisterUserHandler) -> None:
    """Matches Gherkin: 'Successfully register a new account'."""
    command = RegisterUserCommand(
        email="newuser@example.com", password="StrongPass1", confirm_password="StrongPass1"
    )
    result = await handler.handle(command)
    assert str(result.user.email) == "newuser@example.com"
    assert result.user.password_hash == "hashed:StrongPass1"
    assert result.tokens.access_token == "fake-access"


@pytest.mark.asyncio
async def test_duplicate_email_rejected(handler: RegisterUserHandler) -> None:
    """Matches Gherkin: 'Attempt to register with an already-registered email'."""
    command = RegisterUserCommand(
        email="existing@example.com", password="StrongPass1", confirm_password="StrongPass1"
    )
    await handler.handle(command)

    with pytest.raises(EmailAlreadyExistsError):
        await handler.handle(command)


@pytest.mark.asyncio
async def test_weak_password_rejected(handler: RegisterUserHandler) -> None:
    """Matches Gherkin: 'Attempt to register with a weak password'."""
    command = RegisterUserCommand(email="a@example.com", password="12345", confirm_password="12345")
    with pytest.raises(WeakPasswordError):
        await handler.handle(command)


@pytest.mark.asyncio
async def test_password_mismatch_rejected(handler: RegisterUserHandler) -> None:
    command = RegisterUserCommand(
        email="a@example.com", password="StrongPass1", confirm_password="Different1"
    )
    with pytest.raises(PasswordMismatchError):
        await handler.handle(command)


@pytest.mark.asyncio
async def test_invalid_email_format_rejected(handler: RegisterUserHandler) -> None:
    command = RegisterUserCommand(
        email="not-an-email", password="StrongPass1", confirm_password="StrongPass1"
    )
    with pytest.raises(InvalidEmailError):
        await handler.handle(command)
