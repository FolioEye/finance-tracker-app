"""QA Lead mandatory security sweep for FINTRACK-21 (Weekly Recommendation
Engine), run at the real API level (TestClient -> real router -> real
handler -> real SQLite-backed repositories).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection, XSS, auth bypass, IDOR. Same shape as
tests/security/test_insights_security.py: this endpoint is read-only with
no free-text or caller-supplied request field at all (no path param, no
query param, no body) -- the only input is the caller's own JWT -- so
there is no SQL injection or XSS input surface to test here, unlike
budgets/transactions which accept free-text category/note fields. That
absence is asserted implicitly by there being no test for it (matching
test_insights_security.py's documented precedent), while auth bypass and
IDOR -- which fully apply -- get the real coverage below.
"""
from __future__ import annotations

import uuid

import jwt as pyjwt


def _register_and_login(client, email: str, password: str = "StrongPass1") -> str:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "confirm_password": password},
    )
    assert resp.status_code == 201, resp.text
    login_resp = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert login_resp.status_code == 200, login_resp.text
    return login_resp.json()["access_token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_budget(client, token: str, category: str, monthly_limit: str):
    return client.post(
        "/api/v1/budgets",
        json={"category": category, "monthly_limit": monthly_limit},
        headers=_auth(token),
    )


def _create_transaction(client, token: str, amount: str, category: str, transaction_date: str):
    return client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": category, "transaction_date": transaction_date},
        headers=_auth(token),
    )


def _recommendation(client, token: str | None = None):
    headers = _auth(token) if token else {}
    return client.get("/api/v1/recommendations/weekly", headers=headers)


# ---------------------------------------------------------------------------
# Auth bypass
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected(client) -> None:
    resp = _recommendation(client)
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.get(
        "/api/v1/recommendations/weekly", headers={"Authorization": "NotBearer sometoken"}
    )
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.get("/api/v1/recommendations/weekly", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.get(
        "/api/v1/recommendations/weekly", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401


def test_auth_bypass_refresh_token_rejected_as_access_token(client) -> None:
    """A refresh-typed token presented as a bearer access token must be
    rejected -- same convention as get_current_user_id's existing
    handling for every other authenticated endpoint."""
    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "refresh", "jti": str(uuid.uuid4())},
        "test-secret-key-not-for-production-use-only",
        algorithm="HS256",
    )
    resp = client.get(
        "/api/v1/recommendations/weekly", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401


def test_auth_bypass_expired_token_rejected(client) -> None:
    forged = pyjwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "type": "access",
            "jti": str(uuid.uuid4()),
            "exp": 1,  # 1970 -- already expired
        },
        "test-secret-key-not-for-production-use-only",
        algorithm="HS256",
    )
    resp = client.get(
        "/api/v1/recommendations/weekly", headers={"Authorization": f"Bearer {forged}"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- there is no account-scoped path or body parameter for an
# attacker to manipulate at all (same shape as insights). The only
# possible IDOR vector is whether the response ever reflects another
# user's budget/subscription/transaction data; checked directly.
# ---------------------------------------------------------------------------


def test_idor_recommendation_never_reflects_another_users_budget_risk(client) -> None:
    victim_token = _register_and_login(client, "reco-idor-sec-victim@example.com")
    attacker_token = _register_and_login(client, "reco-idor-sec-attacker@example.com")
    assert _create_budget(client, victim_token, "SecretCategory", "50.00").status_code == 201
    assert (
        _create_transaction(client, victim_token, "49.00", "SecretCategory", "2026-07-05").status_code
        == 201
    )

    attacker_resp = _recommendation(client, attacker_token)
    assert attacker_resp.status_code == 200, attacker_resp.text
    body = attacker_resp.json()
    assert body["type"] == "NEUTRAL"
    assert body["category"] != "SecretCategory"
    assert "SecretCategory" not in (body.get("message") or "")


def test_idor_recommendation_response_never_contains_a_foreign_category_name(client) -> None:
    other_token = _register_and_login(client, "reco-idor-sec-other@example.com")
    my_token = _register_and_login(client, "reco-idor-sec-me@example.com")
    assert _create_budget(client, other_token, "OtherPersonBudget", "10.00").status_code == 201
    assert (
        _create_transaction(client, other_token, "9.50", "OtherPersonBudget", "2026-07-05").status_code
        == 201
    )
    assert _create_budget(client, my_token, "MyBudget", "100.00").status_code == 201
    assert _create_transaction(client, my_token, "20.00", "MyBudget", "2026-07-05").status_code == 201

    my_resp = _recommendation(client, my_token)
    assert my_resp.status_code == 200, my_resp.text
    body = my_resp.json()
    # My spend (20%) doesn't clear BUDGET_RISK_THRESHOLD_PCT, so I should
    # be NEUTRAL -- and the other user's budget must never appear either
    # way.
    assert body["category"] != "OtherPersonBudget"
