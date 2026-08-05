"""Unit tests for GoogleIdTokenVerifier and AppleIdTokenVerifier.
Google's verify_oauth2_token call and Apple's JWKS fetch are both faked at
the boundary per constraint matrix -- no real network calls. Apple's path
exercises real JWT signature verification (PyJWT + a locally generated
RSA keypair), not a mocked jwt.decode, so the actual verification logic
is genuinely under test.
"""
from __future__ import annotations

import json
import time

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from apps.api.infrastructure.security.oauth_verifier import (
    APPLE_ISSUER,
    AppleIdTokenVerifier,
    GoogleIdTokenVerifier,
    OAuthTokenInvalidError,
)


def _async_return(value):
    async def _inner():
        return value

    return _inner


# ---------------------------------------------------------------------------
# Google
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_google_verifier_returns_identity_on_valid_claims(monkeypatch) -> None:
    def fake_verify_oauth2_token(token, request, audience):
        assert audience == "test-client-id"
        return {
            "iss": "https://accounts.google.com",
            "sub": "g-sub-123",
            "email": "user@example.com",
            "email_verified": True,
        }

    monkeypatch.setattr(
        "apps.api.infrastructure.security.oauth_verifier.google_id_token.verify_oauth2_token",
        fake_verify_oauth2_token,
    )

    verifier = GoogleIdTokenVerifier(client_id="test-client-id")
    identity = await verifier.verify("fake-token")

    assert identity.provider == "google"
    assert identity.subject == "g-sub-123"
    assert identity.email == "user@example.com"
    assert identity.email_verified is True


@pytest.mark.asyncio
async def test_google_verifier_rejects_wrong_issuer(monkeypatch) -> None:
    def fake_verify_oauth2_token(token, request, audience):
        return {"iss": "https://evil.example.com", "sub": "g-sub", "email": "u@example.com"}

    monkeypatch.setattr(
        "apps.api.infrastructure.security.oauth_verifier.google_id_token.verify_oauth2_token",
        fake_verify_oauth2_token,
    )

    verifier = GoogleIdTokenVerifier(client_id="test-client-id")
    with pytest.raises(OAuthTokenInvalidError):
        await verifier.verify("fake-token")


@pytest.mark.asyncio
async def test_google_verifier_wraps_bad_signature_as_invalid_token(monkeypatch) -> None:
    def fake_verify_oauth2_token(token, request, audience):
        raise ValueError("Token has invalid signature")

    monkeypatch.setattr(
        "apps.api.infrastructure.security.oauth_verifier.google_id_token.verify_oauth2_token",
        fake_verify_oauth2_token,
    )

    verifier = GoogleIdTokenVerifier(client_id="test-client-id")
    with pytest.raises(OAuthTokenInvalidError):
        await verifier.verify("fake-token")


def test_google_verifier_requires_client_id() -> None:
    with pytest.raises(ValueError):
        GoogleIdTokenVerifier(client_id="")


# ---------------------------------------------------------------------------
# Apple -- real RSA keypair + real PyJWT signature verification, only the
# network JWKS fetch is faked.
# ---------------------------------------------------------------------------


def _make_apple_test_token(private_key, kid: str, **claim_overrides) -> str:
    now = int(time.time())
    claims = {
        "iss": APPLE_ISSUER,
        "aud": "com.fintrack.web",
        "sub": "a-sub-123",
        "email": "user@example.com",
        "email_verified": "true",
        "iat": now,
        "exp": now + 3600,
    }
    claims.update(claim_overrides)
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


@pytest.fixture
def apple_keypair():
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    kid = "test-key-1"
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    jwks = {"keys": [jwk]}
    return private_key, kid, jwks


@pytest.mark.asyncio
async def test_apple_verifier_returns_identity_for_valid_token(monkeypatch, apple_keypair) -> None:
    private_key, kid, jwks = apple_keypair
    token = _make_apple_test_token(private_key, kid)

    verifier = AppleIdTokenVerifier(client_ids=("com.fintrack.web",))
    monkeypatch.setattr(verifier, "_get_jwks", _async_return(jwks))

    identity = await verifier.verify(token)

    assert identity.provider == "apple"
    assert identity.subject == "a-sub-123"
    assert identity.email == "user@example.com"
    assert identity.email_verified is True


@pytest.mark.asyncio
async def test_apple_verifier_rejects_wrong_audience(monkeypatch, apple_keypair) -> None:
    private_key, kid, jwks = apple_keypair
    token = _make_apple_test_token(private_key, kid, aud="com.someone.else")

    verifier = AppleIdTokenVerifier(client_ids=("com.fintrack.web",))
    monkeypatch.setattr(verifier, "_get_jwks", _async_return(jwks))

    with pytest.raises(OAuthTokenInvalidError):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_apple_verifier_rejects_expired_token(monkeypatch, apple_keypair) -> None:
    private_key, kid, jwks = apple_keypair
    now = int(time.time())
    token = _make_apple_test_token(private_key, kid, iat=now - 7200, exp=now - 3600)

    verifier = AppleIdTokenVerifier(client_ids=("com.fintrack.web",))
    monkeypatch.setattr(verifier, "_get_jwks", _async_return(jwks))

    with pytest.raises(OAuthTokenInvalidError):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_apple_verifier_rejects_unknown_kid(monkeypatch, apple_keypair) -> None:
    private_key, kid, jwks = apple_keypair
    token = _make_apple_test_token(private_key, "a-different-kid-not-in-jwks")

    verifier = AppleIdTokenVerifier(client_ids=("com.fintrack.web",))
    monkeypatch.setattr(verifier, "_get_jwks", _async_return(jwks))

    with pytest.raises(OAuthTokenInvalidError):
        await verifier.verify(token)


@pytest.mark.asyncio
async def test_apple_verifier_normalises_string_email_verified_claim(monkeypatch, apple_keypair) -> None:
    """Apple sometimes sends email_verified as the string "false" rather
    than a real boolean -- must not be treated as truthy."""
    private_key, kid, jwks = apple_keypair
    token = _make_apple_test_token(private_key, kid, email_verified="false")

    verifier = AppleIdTokenVerifier(client_ids=("com.fintrack.web",))
    monkeypatch.setattr(verifier, "_get_jwks", _async_return(jwks))

    identity = await verifier.verify(token)
    assert identity.email_verified is False


def test_apple_verifier_requires_client_ids() -> None:
    with pytest.raises(ValueError):
        AppleIdTokenVerifier(client_ids=())
