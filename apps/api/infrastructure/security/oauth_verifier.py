"""OAuth ID token verification -- Google and Apple. FINTRACK-42/43 (ADR-016).

Both providers hand back a signed ID token (a JWT) after the user
authenticates on the frontend (Google Identity Services / Apple's JS SDK).
This module verifies that token ourselves against the provider's own
public keys -- no server-side OAuth "authorization code" exchange, no
client secret, no managed auth provider needed. See
docs/adr/ADR-016-oauth-authentication-strategy.md for why.
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable, TypeVar

import httpx
import jwt
from google.auth import exceptions as google_auth_exceptions
from google.auth.transport.requests import Request as GoogleAuthRequest
from google.oauth2 import id_token as google_id_token

logger = logging.getLogger("fintrack.oauth")

T = TypeVar("T")

APPLE_ISSUER = "https://appleid.apple.com"
APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
GOOGLE_ISSUERS = ("accounts.google.com", "https://accounts.google.com")


class OAuthTokenInvalidError(Exception):
    """Raised for any ID token that fails signature, issuer, audience, or
    expiry verification. Deliberately generic -- callers must not surface
    provider-internal failure detail to the end user (mirrors
    InvalidCredentialsError's no-enumeration rationale in login_user.py)."""


class OAuthProviderUnavailableError(Exception):
    """Raised when the provider's key-discovery endpoint can't be reached
    after retries -- distinct from OAuthTokenInvalidError because this is
    a transient infrastructure failure (should map to 503, not 401)."""


@dataclass(frozen=True)
class OAuthIdentity:
    provider: str  # "google" | "apple"
    subject: str  # provider's stable user id (the "sub" claim)
    email: str
    email_verified: bool


async def _with_retries(fn: Callable[[], Awaitable[T]], attempts: int = 3) -> T:
    """Exponential backoff with jitter, 3 attempts, per constraint matrix.
    Used for Apple's JWKS fetch (a plain httpx call we own end to end).
    Google's verify_oauth2_token is not routed through this -- google-auth
    manages its own certificate caching/retry internally, and its failures
    are reported as a generic ValueError rather than a distinguishable
    transient-vs-permanent exception, so wrapping it here would just add a
    fixed 3x latency to every genuinely-invalid-token rejection.
    """
    last_exc: Exception | None = None
    for attempt in range(attempts):
        try:
            return await fn()
        except httpx.HTTPError as exc:
            last_exc = exc
            if attempt == attempts - 1:
                break
            backoff = (2 ** attempt) + random.uniform(0, 0.5)
            logger.warning(
                "oauth_provider_retry",
                extra={"context": {"attempt": attempt + 1, "backoff_seconds": round(backoff, 2)}},
            )
            await asyncio.sleep(backoff)
    raise OAuthProviderUnavailableError("OAuth provider unavailable") from last_exc


class GoogleIdTokenVerifier:
    """Verifies a Google Identity Services ID token."""

    def __init__(self, client_id: str) -> None:
        if not client_id:
            raise ValueError("google_oauth_client_id must be set via environment")
        self._client_id = client_id

    async def verify(self, id_token_str: str) -> OAuthIdentity:
        try:
            # google-auth's verify_oauth2_token is a blocking call (uses
            # `requests` internally for the transport) -- offloaded to a
            # worker thread so this coroutine doesn't block the event
            # loop, per the async-I/O-throughout constraint.
            claims = await asyncio.to_thread(
                google_id_token.verify_oauth2_token,
                id_token_str,
                GoogleAuthRequest(),
                self._client_id,
            )
        except google_auth_exceptions.TransportError as exc:
            raise OAuthProviderUnavailableError(
                "Could not reach Google for token verification"
            ) from exc
        except ValueError as exc:
            # google-auth raises plain ValueError for a bad signature, an
            # expired token, or an audience/issuer mismatch -- all folded
            # into the same generic error here.
            raise OAuthTokenInvalidError("Invalid Google ID token") from exc

        if claims.get("iss") not in GOOGLE_ISSUERS:
            raise OAuthTokenInvalidError("Invalid Google ID token issuer")

        subject = claims.get("sub")
        email = claims.get("email")
        if not subject or not email:
            raise OAuthTokenInvalidError("Google ID token missing required claims")

        return OAuthIdentity(
            provider="google",
            subject=subject,
            email=email,
            email_verified=bool(claims.get("email_verified", False)),
        )


class AppleIdTokenVerifier:
    """Verifies an Apple "Sign in with Apple" identity token.

    Apple's JWKS is fetched fresh (and cached briefly) rather than shipped
    as a static keyset -- Apple rotates these keys on their own schedule,
    same reasoning as any other provider-hosted JWKS. The cache lives on
    the instance, not a module global -- see dependencies.py for why a
    single verifier instance is still reused across requests (an
    lru_cache-wrapped factory, the same idiom config.get_settings()
    already uses) rather than rebuilt per request.
    """

    def __init__(self, client_ids: tuple[str, ...], jwks_ttl_seconds: int = 3600) -> None:
        if not client_ids:
            raise ValueError("apple_oauth_client_ids must be set via environment")
        self._client_ids = client_ids
        self._jwks_ttl_seconds = jwks_ttl_seconds
        self._jwks_cache: dict[str, Any] | None = None
        self._jwks_fetched_at: float = 0.0

    async def _get_jwks(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks_cache is not None and (now - self._jwks_fetched_at) < self._jwks_ttl_seconds:
            return self._jwks_cache

        async def _fetch() -> dict[str, Any]:
            async with httpx.AsyncClient(timeout=5.0) as client:
                response = await client.get(APPLE_JWKS_URL)
                response.raise_for_status()
                return response.json()

        jwks = await _with_retries(_fetch)
        self._jwks_cache = jwks
        self._jwks_fetched_at = now
        return jwks

    async def verify(self, id_token_str: str) -> OAuthIdentity:
        jwks = await self._get_jwks()

        try:
            unverified_header = jwt.get_unverified_header(id_token_str)
        except jwt.InvalidTokenError as exc:
            raise OAuthTokenInvalidError("Malformed Apple ID token") from exc

        signing_key = None
        for key in jwks.get("keys", []):
            if key.get("kid") == unverified_header.get("kid"):
                signing_key = jwt.PyJWK(key).key
                break
        if signing_key is None:
            raise OAuthTokenInvalidError("No matching Apple signing key found")

        try:
            claims = jwt.decode(
                id_token_str,
                key=signing_key,
                algorithms=["RS256"],
                audience=list(self._client_ids),
                issuer=APPLE_ISSUER,
            )
        except jwt.InvalidTokenError as exc:
            raise OAuthTokenInvalidError("Invalid Apple ID token") from exc

        subject = claims.get("sub")
        email = claims.get("email")
        if not subject or not email:
            raise OAuthTokenInvalidError("Apple ID token missing required claims")

        # Apple's email_verified claim is sometimes a string "true"/"false"
        # rather than a real boolean, depending on flow -- normalise
        # explicitly instead of relying on Python truthiness of the string
        # "false" (which is truthy).
        email_verified_claim = claims.get("email_verified", False)
        email_verified = (
            email_verified_claim is True or str(email_verified_claim).lower() == "true"
        )

        return OAuthIdentity(
            provider="apple",
            subject=subject,
            email=email,
            email_verified=email_verified,
        )
