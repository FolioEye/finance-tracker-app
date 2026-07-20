"""QA Lead mandatory security sweep for FINTRACK-22 (Threshold-Based
Alerts), run at the real API level (TestClient -> real router -> real
Pydantic validation -> real handler -> real SQLite-backed repository).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on
every text input, auth bypass, IDOR. Structure matches
tests/security/test_budgets_security.py and
tests/security/test_transactions_security.py.

Alerts have a narrower attack surface than budgets/transactions: there is
no direct create-alert endpoint (alerts are only ever produced as a side
effect of transaction creation), so the only user-controlled input on
this router is the alert_id path parameter on the dismiss endpoint. The
category field on an alert response is copied verbatim from an
already-validated Transaction/Budget row (see domain.models.alert.Alert's
docstring) -- this suite still verifies that inherited value is safely
inert when it reaches an alert response, exactly as
test_budgets_security.py verifies for Budget.category.
"""
from __future__ import annotations

import uuid

SQLI_PAYLOAD = "'; DROP TABLE alerts; --"
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


def _list_alerts(client, token: str):
    return client.get("/api/v1/alerts", headers=_auth(token))


# ---------------------------------------------------------------------------
# SQL injection -- the only user-controlled field on this router is the
# alert_id path parameter (dismiss endpoint). FastAPI's UUID type
# validation rejects a non-UUID path segment before it ever reaches
# application code, which is itself the correct defence here.
# ---------------------------------------------------------------------------


def test_sql_injection_shaped_alert_id_path_param_rejected_as_malformed_uuid(client) -> None:
    """The payload legitimately appears in FastAPI's own validation-error
    body (it echoes back the rejected input value, standard Pydantic
    behaviour for a 422) -- that's not a reflection risk in a JSON-only
    API. The actual security property under test is that this never
    reaches the handler or a query at all: a clean 422 with a well-formed
    JSON body, not a 500 or a raw traceback."""
    token = _register_and_login(client, "alert-sqli-path@example.com")
    resp = client.post(f"/api/v1/alerts/{SQLI_PAYLOAD}/dismiss", headers=_auth(token))
    assert resp.status_code == 422  # FastAPI's UUID path validation, never reaches the handler
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"][0]["type"] == "uuid_parsing"


def test_sql_injection_shaped_category_inherited_from_a_transaction_does_not_disturb_other_users_data(
    client,
) -> None:
    """If a SQLi-shaped category ever reached an unparameterised query
    somewhere in the alert-evaluation path, a DROP TABLE would take out
    every alert, not just one user's. A real, unrelated user's alert
    surviving right after -- and still dismissible -- is the strongest
    evidence the table is intact. (The category itself is rejected at
    Transaction creation, same SuspiciousInputError as
    test_transactions_security.py -- this test confirms that rejection
    doesn't leave any alert-side side effect behind either.)
    """
    victim_token = _register_and_login(client, "alert-sqli-bystander-victim@example.com")
    _create_budget(client, victim_token, "Groceries", "100.00")
    _create_transaction(client, victim_token, "95.00", "Groceries", "2026-07-10")
    victim_alert_id = _list_alerts(client, victim_token).json()["items"][0]["id"]

    attacker_token = _register_and_login(client, "alert-sqli-bystander-attacker@example.com")
    injection_resp = _create_transaction(client, attacker_token, "50.00", SQLI_PAYLOAD, "2026-07-10")
    assert injection_resp.status_code == 400  # rejected at Transaction.new(), no alert side effect

    dismiss_resp = client.post(f"/api/v1/alerts/{victim_alert_id}/dismiss", headers=_auth(victim_token))
    assert dismiss_resp.status_code == 204


# ---------------------------------------------------------------------------
# XSS -- category is free text and is NOT stripped of markup once it
# reaches an alert (only the SQLi-shaped pattern is rejected, inherited
# from Transaction/Budget validation). Safe today because the API is
# JSON-only (Content-Type: application/json) with no HTML-rendering
# surface -- same documented boundary as test_budgets_security.py's XSS
# tests: whichever future story renders alerts in a browser MUST
# escape/sanitise on render (DOMPurify, per the constraint matrix).
# ---------------------------------------------------------------------------


def test_xss_payload_in_category_is_inert_when_returned_in_an_alert(client) -> None:
    token = _register_and_login(client, "alert-xss-category@example.com")
    _create_budget(client, token, XSS_PAYLOAD, "100.00")
    resp = _create_transaction(client, token, "95.00", XSS_PAYLOAD, "2026-07-10")
    assert resp.status_code == 201, resp.text

    alerts_resp = _list_alerts(client, token)
    assert alerts_resp.status_code == 200
    assert alerts_resp.headers["content-type"].startswith("application/json")
    categories = [a["category"] for a in alerts_resp.json()["items"]]
    assert XSS_PAYLOAD in categories  # stored/returned verbatim, as data, never executed


# ---------------------------------------------------------------------------
# Auth bypass -- both alert endpoints
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected_on_list(client) -> None:
    resp = client.get("/api/v1/alerts")
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_missing_token_rejected_on_dismiss(client) -> None:
    resp = client.post(f"/api/v1/alerts/{uuid.uuid4()}/dismiss")
    assert resp.status_code == 401


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.get("/api/v1/alerts", headers={"Authorization": "NotBearer sometoken"})
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.get("/api/v1/alerts", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.get("/api/v1/alerts", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_auth_bypass_expired_token_rejected_on_dismiss(client) -> None:
    import jwt as pyjwt

    from apps.api.config import get_settings

    settings = get_settings()
    expired = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4()), "exp": 1},  # epoch second 1 -- long expired
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.post(f"/api/v1/alerts/{uuid.uuid4()}/dismiss", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- dismiss and list isolation across users
# ---------------------------------------------------------------------------


def test_idor_cannot_dismiss_another_users_alert(client) -> None:
    victim_token = _register_and_login(client, "alert-idor-dismiss-victim@example.com")
    attacker_token = _register_and_login(client, "alert-idor-dismiss-attacker@example.com")
    _create_budget(client, victim_token, "Private", "100.00")
    _create_transaction(client, victim_token, "95.00", "Private", "2026-07-10")
    alert_id = _list_alerts(client, victim_token).json()["items"][0]["id"]

    resp = client.post(f"/api/v1/alerts/{alert_id}/dismiss", headers=_auth(attacker_token))
    assert resp.status_code == 404  # not 403 -- can't be used to confirm the id exists

    victim_items = _list_alerts(client, victim_token).json()["items"]
    assert victim_items[0]["dismissed_at"] is None  # untouched


def test_idor_list_never_leaks_another_users_alerts(client) -> None:
    victim_token = _register_and_login(client, "alert-idor-list-victim@example.com")
    attacker_token = _register_and_login(client, "alert-idor-list-attacker@example.com")
    _create_budget(client, victim_token, "Private", "100.00")
    _create_transaction(client, victim_token, "95.00", "Private", "2026-07-10")

    attacker_items = _list_alerts(client, attacker_token).json()["items"]
    assert attacker_items == []


def test_idor_a_forged_alert_id_belonging_to_no_one_returns_404_not_500(client) -> None:
    """A well-formed-but-nonexistent UUID must fail the same way a real
    other-user id does (404), never leak a stack trace or a distinct
    error shape that would help an attacker distinguish the two cases."""
    token = _register_and_login(client, "alert-idor-forged-uuid@example.com")
    resp = client.post(f"/api/v1/alerts/{uuid.uuid4()}/dismiss", headers=_auth(token))
    assert resp.status_code == 404
