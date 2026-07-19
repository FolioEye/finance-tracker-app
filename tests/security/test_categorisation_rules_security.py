"""QA Lead mandatory security sweep for FINTRACK-17 (AI Auto-Categorisation
Rules Engine), run at the real API level (TestClient -> real router -> real
Pydantic validation -> real handler -> real SQLite-backed repository).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on every
text input, auth bypass, IDOR. This story's only mutating endpoint is
POST /api/v1/categorisation-rules (no GET/list/delete yet, per ADR-012's
documented deferred scope) -- IDOR here means one user's rule leaking into
another user's auto-categorisation matching, which is covered in depth in
tests/integration/test_categorisation_rules_api.py's cross-user isolation
tests; this file focuses on injection and auth-bypass, matching
tests/security/test_transactions_security.py's structure.
"""
from __future__ import annotations

import uuid

SQLI_PAYLOAD = "'; DROP TABLE rules; --"
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


def _create_rule(client, token: str, merchant_pattern: str, category: str):
    return client.post(
        "/api/v1/categorisation-rules",
        json={"merchant_pattern": merchant_pattern, "category": category},
        headers=_auth(token),
    )


# ---------------------------------------------------------------------------
# SQL injection -- merchant_pattern field (matches the BA's Gherkin
# scenario 4 exactly)
# ---------------------------------------------------------------------------


def test_sql_injection_in_merchant_pattern_field_rejected(client) -> None:
    token = _register_and_login(client, "catrule-sqli-merchant@example.com")
    resp = _create_rule(client, token, SQLI_PAYLOAD, "Groceries")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid characters detected"


def test_sql_injection_in_category_field_rejected(client) -> None:
    token = _register_and_login(client, "catrule-sqli-category@example.com")
    resp = _create_rule(client, token, "Starbucks", SQLI_PAYLOAD)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid characters detected"


def test_sql_injection_payload_never_reflected_in_response(client) -> None:
    token = _register_and_login(client, "catrule-sqli-reflection@example.com")
    resp = _create_rule(client, token, SQLI_PAYLOAD, "Groceries")
    assert SQLI_PAYLOAD not in resp.text


def test_sql_injection_does_not_disturb_other_users_data(client) -> None:
    """If the payload had reached a query unparameterised, a DROP TABLE
    would take out every rule, not just fail to create one. A real,
    unrelated user's rule surviving right after -- and still doing its job
    -- is the strongest evidence the table is intact."""
    victim_token = _register_and_login(client, "catrule-sqli-bystander-victim@example.com")
    victim_rule = _create_rule(client, victim_token, "Starbucks", "Coffee & Dining")
    assert victim_rule.status_code == 201

    attacker_token = _register_and_login(client, "catrule-sqli-bystander-attacker@example.com")
    injection_resp = _create_rule(client, attacker_token, SQLI_PAYLOAD, "Groceries")
    assert injection_resp.status_code == 400

    victim_stage = client.post(
        "/api/v1/imports",
        files={
            "file": (
                "statement.csv",
                b"Date,Amount,Description,Category\n2026-07-01,10.00,STARBUCKS #1,\n",
                "text/csv",
            )
        },
        headers=_auth(victim_token),
    )
    assert victim_stage.status_code == 201, victim_stage.text
    assert victim_stage.json()["rows"][0]["category"] == "Coffee & Dining"


def test_security_event_is_logged_on_sql_injection_attempt(client, caplog) -> None:
    token = _register_and_login(client, "catrule-sqli-log@example.com")
    _create_rule(client, token, SQLI_PAYLOAD, "Groceries")
    assert any(
        "categorisation_rule_suspicious_input_rejected" in record.getMessage()
        for record in caplog.records
    )


# ---------------------------------------------------------------------------
# XSS -- merchant_pattern/category are free text and are NOT stripped of
# markup (only the SQLi-shaped pattern is rejected, per ADR-012, same
# precedent as ADR-010's transaction fields). Safe today because the API is
# JSON-only (Content-Type: application/json) with no HTML-rendering
# surface. Documented explicitly rather than silently skipped: whichever
# future story renders these fields in a browser MUST escape/sanitise on
# render (DOMPurify, per the constraint matrix).
# ---------------------------------------------------------------------------


def test_xss_payload_in_merchant_pattern_is_stored_as_inert_text_not_executed(client) -> None:
    token = _register_and_login(client, "catrule-xss-merchant@example.com")
    resp = _create_rule(client, token, XSS_PAYLOAD, "Groceries")
    assert resp.status_code == 201, resp.text
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["merchant_pattern"] == XSS_PAYLOAD.upper()  # stored verbatim (upper-cased), as data


def test_xss_payload_in_category_is_stored_as_inert_text_not_executed(client) -> None:
    token = _register_and_login(client, "catrule-xss-category@example.com")
    resp = _create_rule(client, token, "Starbucks", XSS_PAYLOAD)
    assert resp.status_code == 201, resp.text
    assert resp.json()["category"] == XSS_PAYLOAD  # stored verbatim, as data


# ---------------------------------------------------------------------------
# Auth bypass
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected_on_create(client) -> None:
    resp = client.post(
        "/api/v1/categorisation-rules",
        json={"merchant_pattern": "Starbucks", "category": "Coffee & Dining"},
    )
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.post(
        "/api/v1/categorisation-rules",
        json={"merchant_pattern": "Starbucks", "category": "Coffee & Dining"},
        headers={"Authorization": "NotBearer sometoken"},
    )
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.post(
        "/api/v1/categorisation-rules",
        json={"merchant_pattern": "Starbucks", "category": "Coffee & Dining"},
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
        "/api/v1/categorisation-rules",
        json={"merchant_pattern": "Starbucks", "category": "Coffee & Dining"},
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- this story exposes no GET/list/delete endpoint for a malicious
# user to directly query another user's rules against (recorded here so a
# future GET /categorisation-rules endpoint inherits this expectation
# rather than reinventing it). The real cross-user risk for this story --
# whether one user's rule can leak into another user's auto-categorisation
# matching -- is exercised end-to-end in
# tests/integration/test_categorisation_rules_api.py.
# ---------------------------------------------------------------------------


def test_idor_no_get_or_list_endpoint_exists_yet_documented(client) -> None:
    token = _register_and_login(client, "catrule-idor-no-get@example.com")
    resp = client.get("/api/v1/categorisation-rules", headers=_auth(token))
    assert resp.status_code in (404, 405)  # no route defined for this path
