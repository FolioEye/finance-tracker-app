"""Security-focused tests for FINTRACK-13 -- maps directly to the Gherkin
security scenario (SQL injection in the email field) plus a
password-never-logged verification that the constraint matrix requires.
"""
from __future__ import annotations

import logging

import pytest

from apps.api.application.commands.register_user import RegisterUserCommand, RegisterUserHandler
from apps.api.domain.models.user import InvalidEmailError
from tests.unit.test_register_user import FakePasswordHasher, FakeTokenService, FakeUserRepository


@pytest.fixture
def handler() -> RegisterUserHandler:
    return RegisterUserHandler(
        user_repository=FakeUserRepository(),
        password_hasher=FakePasswordHasher(),
        token_service=FakeTokenService(),
    )


@pytest.mark.asyncio
async def test_sql_injection_in_email_is_rejected_not_executed(handler: RegisterUserHandler) -> None:
    """Matches Gherkin: 'Attempt SQL injection in email field during registration'.

    The Email value object's format regex rejects this outright before any
    query is built -- and even if it somehow reached the repository, the
    SQLAlchemy layer only ever uses parameterised queries (see
    sqlalchemy_user_repository.py), so no string-concatenation path exists
    for this input to reach the database at all.
    """
    command = RegisterUserCommand(
        email="'; DROP TABLE users; --", password="StrongPass1", confirm_password="StrongPass1"
    )
    with pytest.raises(InvalidEmailError):
        await handler.handle(command)


@pytest.mark.asyncio
async def test_password_never_appears_in_log_output(handler: RegisterUserHandler, caplog) -> None:
    caplog.set_level(logging.DEBUG)
    command = RegisterUserCommand(
        email="secure@example.com", password="SuperSecret123", confirm_password="SuperSecret123"
    )
    await handler.handle(command)

    for record in caplog.records:
        assert "SuperSecret123" not in record.getMessage()
        assert "SuperSecret123" not in str(record.__dict__)
