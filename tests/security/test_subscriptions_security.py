"""QA Lead mandatory security sweep for FINTRACK-18 (Subscription /
Recurring-Charge Detection), run at the real API level (TestClient ->
real router -> real Pydantic validation -> real handler -> real
SQLite-backed repository).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on
every text input, auth bypass, IDOR. Structure matches
tests/security/test_alerts_security.py.

Subscriptions have a narrow attack surface, same shape as Alert: there is
no direct create-subscription endpoint (rows are only ever produced as a
side effect of transaction creation), so the only directly user-controlled
input on this router is the subscription_id path parameter (confirm/
dismiss/mark-not-subscription). The merchant field is derived from
Transaction.note (already validated/sanitised at Transaction creation --
see domain.models.subscription's docstring) -- this suite verifies that
inherited value stays safely inert wherever it appears on this router's
responses, same pattern test_alerts_security.py uses for Alert.category.
"""
from __future__ import annotations

import uuid

SQLI_PAYLOAD = "'; DROP TABLE subscriptions; --"
XSS_PAYLOAD = "<script>alert('xss')</script>"


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


def _create_transaction(client, token: str, amount: str, transaction_date: str, note: str):
    return client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": "Bills", "transaction_date": transaction_date, "note": note},
        headers=_auth(token),
    )


def _list_subscriptions(client, token: str):
    return client.get("/api/v1/subscriptions", headers=_auth(token))


# ---------------------------------------------------------------------------
# SQL injection -- the only directly user-controlled field on this router
# is the subscription_id path parameter. FastAPI's UUID type validation
# rejects a non-UUID path segment before it ever reaches application code.
# ---------------------------------------------------------------------------


def test_sql_injection_shaped_subscription_id_path_param_rejected_as_malformed_uuid(client) -> None:
    """As with test_alerts_security.py's equivalent: the payload
    legitimately appears in FastAPI's own 422 validation-error body
    (standard Pydantic behaviour) -- not a reflection risk in a JSON-only
    API. The security property under test is that this never reaches the
    handler or a query at all."""
    token = _register_and_login(client, "sub-sqli-path@example.com")
    resp = client.post(f"/api/v1/subscriptions/{SQLI_PAYLOAD}/dismiss", headers=_auth(token))
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"][0]["type"] == "uuid_parsing"


def test_sql_injection_shaped_note_is_rejected_at_transaction_creation_not_subscription_detection(client) -> None:
    """CORRECTED (2026-07-23): the first version of this test wrongly
    asserted the SQLi-shaped transaction succeeds (201). It doesn't --
    Transaction.new() runs _reject_if_suspicious() on `note` as well as
    `category` (see apps/api/domain/models/transaction.py), so this is
    rejected with 400 before subscription detection ever sees it, exactly
    like test_alerts_security.py's equivalent test for Alert.category.
    That earlier wrong assertion is almost certainly what was failing in
    CI. The real security property here is: the SQLi-shaped input never
    reaches the merchant-clustering path at all, and an unrelated victim's
    own subscription data is completely unaffected by the attacker's
    rejected attempt."""
    victim_token = _register_and_login(client, "sub-sqli-bystander-victim@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, victim_token, "15.99", d, "Netflix.com")
    assert len(_list_subscriptions(client, victim_token).json()["items"]) == 1

    attacker_token = _register_and_login(client, "sub-sqli-bystander-attacker@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        resp = _create_transaction(client, attacker_token, "9.99", d, SQLI_PAYLOAD)
        assert resp.status_code == 400  # rejected at Transaction.new(), never reaches detection
        assert resp.json()["detail"] == "Invalid characters detected"

    attacker_items = _list_subscriptions(client, attacker_token).json()["items"]
    assert attacker_items == []  # nothing was ever created for the attacker

    victim_items = _list_subscriptions(client, victim_token).json()["items"]
    assert len(victim_items) == 1  # victim's data completely untouched
    assert victim_items[0]["merchant"] == "NETFLIX.COM"


# ---------------------------------------------------------------------------
# XSS -- merchant is free text, inherited from Transaction.note, never
# stripped of markup. Safe today because the API is JSON-only
# (Content-Type: application/json) with no HTML-rendering surface -- same
# documented boundary as test_alerts_security.py's XSS coverage for
# Alert.category. This also IS the BA's own Gherkin security scenario
# (see test_subscriptions_api.py's dedicated mapping); repeated here as
# part of the mandatory sweep checklist for completeness.
# ---------------------------------------------------------------------------


def test_xss_payload_in_merchant_is_inert_when_returned_in_a_subscription(client) -> None:
    token = _register_and_login(client, "sub-xss-merchant@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        resp = _create_transaction(client, token, "9.99", d, XSS_PAYLOAD)
        assert resp.status_code == 201

    subs_resp = _list_subscriptions(client, token)
    assert subs_resp.status_code == 200
    assert subs_resp.headers["content-type"].startswith("application/json")
    merchants = [s["merchant"] for s in subs_resp.json()["items"]]
    assert XSS_PAYLOAD.upper() in merchants  # stored/returned verbatim, as data, never executed


# ---------------------------------------------------------------------------
# Auth bypass -- all four endpoints
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected_on_list(client) -> None:
    resp = client.get("/api/v1/subscriptions")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_missing_token_rejected_on_confirm(client) -> None:
    resp = client.post(f"/api/v1/subscriptions/{uuid.uuid4()}/confirm")
    assert resp.status_code == 401


def test_auth_bypass_missing_token_rejected_on_dismiss(client) -> None:
    resp = client.post(f"/api/v1/subscriptions/{uuid.uuid4()}/dismiss")
    assert resp.status_code == 401


def test_auth_bypass_missing_token_rejected_on_mark_not_subscription(client) -> None:
    resp = client.post(f"/api/v1/subscriptions/{uuid.uuid4()}/mark-not-subscription")
    assert resp.status_code == 401


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.get("/api/v1/subscriptions", headers={"Authorization": "NotBearer sometoken"})
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.get("/api/v1/subscriptions", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_auth_bypass_expired_token_rejected_on_confirm(client) -> None:
    import jwt as pyjwt

    from apps.api.config import get_settings

    settings = get_settings()
    expired = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4()), "exp": 1},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.post(
        f"/api/v1/subscriptions/{uuid.uuid4()}/confirm", headers={"Authorization": f"Bearer {expired}"}
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- confirm/dismiss/mark-not-subscription and list isolation
# ---------------------------------------------------------------------------


def test_idor_cannot_confirm_another_users_subscription(client) -> None:
    victim_token = _register_and_login(client, "sub-idor-confirm-victim@example.com")
    attacker_token = _register_and_login(client, "sub-idor-confirm-attacker@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, victim_token, "15.99", d, "Private Merchant")
    sub_id = _list_subscriptions(client, victim_token).json()["items"][0]["id"]

    resp = client.post(f"/api/v1/subscriptions/{sub_id}/confirm", headers=_auth(attacker_token))
    assert resp.status_code == 404  # not 403 -- can't be used to confirm the id exists

    victim_items = _list_subscriptions(client, victim_token).json()["items"]
    assert victim_items[0]["status"] == "DETECTED"  # untouched


def test_idor_cannot_dismiss_another_users_subscription(client) -> None:
    victim_token = _register_and_login(client, "sub-idor-dismiss-victim@example.com")
    attacker_token = _register_and_login(client, "sub-idor-dismiss-attacker@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, victim_token, "15.99", d, "Private Merchant")
    sub_id = _list_subscriptions(client, victim_token).json()["items"][0]["id"]

    resp = client.post(f"/api/v1/subscriptions/{sub_id}/dismiss", headers=_auth(attacker_token))
    assert resp.status_code == 404

    victim_items = _list_subscriptions(client, victim_token).json()["items"]
    assert victim_items[0]["status"] == "DETECTED"


def test_idor_list_never_leaks_another_users_subscriptions(client) -> None:
    victim_token = _register_and_login(client, "sub-idor-list-victim@example.com")
    attacker_token = _register_and_login(client, "sub-idor-list-attacker@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, victim_token, "15.99", d, "Private Merchant")

    attacker_items = _list_subscriptions(client, attacker_token).json()["items"]
    assert attacker_items == []


def test_idor_a_forged_subscription_id_belonging_to_no_one_returns_404_not_500(client) -> None:
    token = _register_and_login(client, "sub-idor-forged-uuid@example.com")
    resp = client.post(f"/api/v1/subscriptions/{uuid.uuid4()}/confirm", headers=_auth(token))
    assert resp.status_code == 404
