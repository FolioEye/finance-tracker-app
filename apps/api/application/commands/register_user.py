"""RegisterUserCommand + handler -- the use case for FINTRACK-13."""
from __future__ import annotations

from dataclasses import dataclass

from apps.api.domain.models.user import (
    Email,
    User,
    validate_password_strength,
)
from apps.api.domain.repositories.user_repository import (
    EmailAlreadyExistsError,
    UserRepository,
)
from apps.api.infrastructure.security.password_hasher import PasswordHasher
from apps.api.infrastructure.security.token_service import TokenPair, TokenService


class PasswordMismatchError(ValueError):
    """Raised when password and confirm_password do not match."""


@dataclass(frozen=True)
class RegisterUserCommand:
    email: str
    password: str
    confirm_password: str


@dataclass(frozen=True)
class RegisterUserResult:
    user: User
    tokens: TokenPair


class RegisterUserHandler:
    """Orchestrates validation, hashing, persistence, and token issuance.

    Depends only on ports (UserRepository, PasswordHasher, TokenService) --
    no direct infrastructure imports, per hexagonal architecture.
    """

    def __init__(
        self,
        user_repository: UserRepository,
        password_hasher: PasswordHasher,
        token_service: TokenService,
        min_password_length: int = 10,
    ) -> None:
        self._users = user_repository
        self._hasher = password_hasher
        self._tokens = token_service
        self._min_password_length = min_password_length

    async def handle(self, command: RegisterUserCommand) -> RegisterUserResult:
        if command.password != command.confirm_password:
            raise PasswordMismatchError("Passwords do not match")

        # Raises InvalidEmailError on bad format (including SQLi-shaped
        # strings) -- caught by the API layer and mapped to a 400.
        email = Email(command.email)

        # Raises WeakPasswordError with a user-safe message.
        validate_password_strength(command.password, self._min_password_length)

        existing = await self._users.get_by_email(email)
        if existing is not None:
            raise EmailAlreadyExistsError("An account with this email already exists")

        password_hash = self._hasher.hash(command.password)
        user = User.new(email=email, password_hash=password_hash)

        # Repository is the backstop for uniqueness under concurrent
        # requests (DB unique constraint -- see migration 0001). A race
        # that slips past get_by_email above still surfaces as
        # EmailAlreadyExistsError from add().
        await self._users.add(user)

        tokens = self._tokens.issue_pair(user.id)
        return RegisterUserResult(user=user, tokens=tokens)
