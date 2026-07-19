"""QA Lead mandatory security sweep for FINTRACK-20 (Simple Budget
Tracking), run at the real API level (TestClient -> real router -> real
Pydantic validation -> real handler -> real SQLite-backed repository).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on
every text input, auth bypass, IDOR. Budgets touch money (monthly_limit)
and are scoped per-user, so all four apply -- structure matches
tests/security/test_categorisation_rules_security.py and
tests/security/test_transactions_security.py.
"""
from __future__ import annotations

import uuid

SQLI_PAYLOAD = "'; DROP TABLE budgets; --"
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


# ---------------------------------------------------------------------------
# SQL injection -- category field (the only free-text field; monthly_limit
# is numeric and goes through Decimal parsing, not a SQLi surface, but is
# covered by a rejected-non-numeric-string test below for completeness)
# ---------------------------------------------------------------------------


def test_sql_injection_in_category_field_rejected(client) -> None:
    token = _register_and_login(client, "budget-sqli-category@example.com")
    resp = _create_budget(client, token, SQLI_PAYLOAD, "500.00")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid characters detected"


def test_sql_injection_payload_never_reflected_in_response(client) -> None:
    token = _register_and_login(client, "budget-sqli-reflection@example.com")
    resp = _create_budget(client, token, SQLI_PAYLOAD, "500.00")
    assert SQLI_PAYLOAD not in resp.text


def test_sql_injection_does_not_disturb_other_users_data(client) -> None:
    """If the payload had reached a query unparameterised, a DROP TABLE
    would take out every budget, not just fail to create one. A real,
    unrelated user's budget surviving right after -- and still working --
    is the strongest evidence the table is intact."""
    victim_token = _register_and_login(client, "budget-sqli-bystander-victim@example.com")
    victim_budget = _create_budget(client, victim_token, "Groceries", "500.00")
    assert victim_budget.status_code == 201

    attacker_token = _register_and_login(client, "budget-sqli-bystander-attacker@example.com")
    injection_resp = _create_budget(client, attacker_token, SQLI_PAYLOAD, "500.00")
    assert injection_resp.status_code == 400

    victim_overview = client.get("/api/v1/budgets", headers=_auth(victim_token))
    assert victim_overview.status_code == 200
    items = {i["category"]: i for i in victim_overview.json()["items"]}
    assert items["Groceries"]["monthly_limit"] == "500.00"


def test_security_event_is_logged_on_sql_injection_attempt(client, caplog) -> None:
    token = _register_and_login(client, "budget-sqli-log@example.com")
    _create_budget(client, token, SQLI_PAYLOAD, "500.00")
    assert any(
        "budget_suspicious_input_rejected" in record.getMessage() for record in caplog.records
    )


def test_non_numeric_monthly_limit_rejected_not_evaluated_as_an_expression(client) -> None:
    """Guards against a monthly_limit value being passed to something
    like eval() or an unparameterised numeric-context query -- it must be
    rejected as an invalid amount, the same as any other malformed number."""
    token = _register_and_login(client, "budget-sqli-limit-expr@example.com")
    resp = _create_budget(client, token, "Groceries", "1 OR 1=1")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Budget must be a positive amount"


# ---------------------------------------------------------------------------
# XSS -- category is free text and is NOT stripped of markup (only the
# SQLi-shaped pattern is rejected, per ADR-013 following ADR-012/ADR-010's
# precedent). Safe today because the API is JSON-only (Content-Type:
# application/json) with no HTML-rendering surface. Documented explicitly:
# whichever future story renders category in a browser MUST escape/
# sanitise on render (DOMPurify, per the constraint matrix).
# ---------------------------------------------------------------------------


def test_xss_payload_in_category_is_stored_as_inert_text_not_executed(client) -> None:
    token = _register_and_login(client, "budget-xss-category@example.com")
    resp = _create_budget(client, token, XSS_PAYLOAD, "500.00")
    assert resp.status_code == 201, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["category"] == XSS_PAYLOAD  # stored verbatim, as data


def test_xss_payload_in_category_is_inert_when_returned_in_the_overview(client) -> None:
    token = _register_and_login(client, "budget-xss-overview@example.com")
    _create_budget(client, token, XSS_PAYLOAD, "500.00")
    resp = client.get("/api/v1/budgets", headers=_auth(token))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    categories = [i["category"] for i in resp.json()["items"]]
    assert XSS_PAYLOAD in categories


# ---------------------------------------------------------------------------
# Auth bypass -- same four checks across all four budget endpoints
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected_on_create(client) -> None:
    resp = client.post("/api/v1/budgets", json={"category": "Groceries", "monthly_limit": "500.00"})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_missing_token_rejected_on_overview(client) -> None:
    resp = client.get("/api/v1/budgets")
    assert resp.status_code == 401


def test_auth_bypass_missing_token_rejected_on_update(client) -> None:
    resp = client.patch(f"/api/v1/budgets/{uuid.uuid4()}", json={"monthly_limit": "1.00"})
    assert resp.status_code == 401


def test_auth_bypass_missing_token_rejected_on_delete(client) -> None:
    resp = client.delete(f"/api/v1/budgets/{uuid.uuid4()}")
    assert resp.status_code == 401


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.post(
        "/api/v1/budgets",
        json={"category": "Groceries", "monthly_limit": "500.00"},
        headers={"Authorization": "NotBearer sometoken"},
    )
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.post(
        "/api/v1/budgets",
        json={"category": "Groceries", "monthly_limit": "500.00"},
        headers={"Authorization": "Bearer "},
    )
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.post(
        "/api/v1/budgets",
        json={"category": "Groceries", "monthly_limit": "500.00"},
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- update, delete, and read isolation across users
# ---------------------------------------------------------------------------


def test_idor_cannot_edit_another_users_budget(client) -> None:
    victim_token = _register_and_login(client, "budget-idor-edit-victim@example.com")
    attacker_token = _register_and_login(client, "budget-idor-edit-attacker@example.com")
    budget_id = _create_budget(client, victim_token, "Private", "100.00").json()["id"]

    resp = client.patch(
        f"/api/v1/budgets/{budget_id}", json={"monthly_limit": "1.00"}, headers=_auth(attacker_token)
    )
    assert resp.status_code == 404  # not 403 -- can't be used to confirm the id exists

    victim_overview = {
        i["category"]: i
        for i in client.get("/api/v1/budgets", headers=_auth(victim_token)).json()["items"]
    }
    assert victim_overview["Private"]["monthly_limit"] == "100.00"  # untouched


def test_idor_cannot_delete_another_users_budget(client) -> None:
    victim_token = _register_and_login(client, "budget-idor-delete-victim@example.com")
    attacker_token = _register_and_login(client, "budget-idor-delete-attacker@example.com")
    budget_id = _create_budget(client, victim_token, "Private", "100.00").json()["id"]

    resp = client.delete(f"/api/v1/budgets/{budget_id}", headers=_auth(attacker_token))
    assert resp.status_code == 404

    victim_overview = {
        i["category"]: i
        for i in client.get("/api/v1/budgets", headers=_auth(victim_token)).json()["items"]
    }
    assert "Private" in victim_overview  # still exists


def test_idor_overview_never_leaks_another_users_categories_or_spend(client) -> None:
    victim_token = _register_and_login(client, "budget-idor-overview-victim@example.com")
    attacker_token = _register_and_login(client, "budget-idor-overview-attacker@example.com")
    _create_budget(client, victim_token, "Private", "100.00")
    client.post(
        "/api/v1/transactions",
        json={"amount": "999.00", "category": "Private", "transaction_date": "2026-07-10"},
        headers=_auth(victim_token),
    )

    attacker_overview = client.get("/api/v1/budgets", headers=_auth(attacker_token))
    assert attacker_overview.status_code == 200
    assert "Private" not in {i["category"] for i in attacker_overview.json()["items"]}
