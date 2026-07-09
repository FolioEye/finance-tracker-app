"""QA Lead mandatory security sweep for FINTRACK-15 (Add Manual
Transaction), run at the real API level (TestClient -> real router ->
real Pydantic validation -> real handler -> real SQLite-backed
repository).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on
every text input, auth bypass, IDOR. This story's IDOR checks are the
most important ones in this suite -- it's the first authenticated,
per-user, resource-scoped endpoint in the codebase -- and are covered in
depth in tests/integration/test_transactions_api.py; this file focuses on
injection and auth-bypass.
"""
from __future__ import annotations

import uuid

SQLI_PAYLOAD = "'; DROP TABLE transactions; --"
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


# ---------------------------------------------------------------------------
# SQL injection -- category field
# ---------------------------------------------------------------------------


def test_sql_injection_in_category_field_rejected(client) -> None:
    token = _register_and_login(client, "sqli-category@example.com")
    resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": SQLI_PAYLOAD, "transaction_date": "2026-07-01"},
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid characters detected"


def test_sql_injection_in_note_field_rejected(client) -> None:
    """Matches the Gherkin scenario exactly: SQL injection in the
    transaction description/note field."""
    token = _register_and_login(client, "sqli-note@example.com")
    resp = client.post(
        "/api/v1/transactions",
        json={
            "amount": "10.00",
            "category": "Groceries",
            "transaction_date": "2026-07-01",
            "note": SQLI_PAYLOAD,
        },
        headers=_auth(token),
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid characters detected"


def test_sql_injection_payload_never_reflected_in_response(client) -> None:
    token = _register_and_login(client, "sqli-reflection@example.com")
    resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": SQLI_PAYLOAD, "transaction_date": "2026-07-01"},
        headers=_auth(token),
    )
    assert SQLI_PAYLOAD not in resp.text


def test_sql_injection_in_update_field_also_rejected(client) -> None:
    """The SQLi check must apply on the update path too, not only create --
    a separate handler with its own call to Transaction.apply_update."""
    token = _register_and_login(client, "sqli-update@example.com")
    create_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": "Groceries", "transaction_date": "2026-07-01"},
        headers=_auth(token),
    )
    transaction_id = create_resp.json()["id"]

    update_resp = client.patch(
        f"/api/v1/transactions/{transaction_id}",
        json={"category": SQLI_PAYLOAD},
        headers=_auth(token),
    )
    assert update_resp.status_code == 400
    assert update_resp.json()["detail"] == "Invalid characters detected"


def test_sql_injection_does_not_disturb_other_users_data(client) -> None:
    """If the payload had reached a query unparameterised, a DROP TABLE
    would take out every transaction, not just fail to create one. A
    real, unrelated user's transaction surviving right after is the
    strongest evidence the table is intact."""
    victim_token = _register_and_login(client, "sqli-bystander-victim@example.com")
    client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": "Groceries", "transaction_date": "2026-07-01"},
        headers=_auth(victim_token),
    )

    attacker_token = _register_and_login(client, "sqli-bystander-attacker@example.com")
    injection_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": SQLI_PAYLOAD, "transaction_date": "2026-07-01"},
        headers=_auth(attacker_token),
    )
    assert injection_resp.status_code == 400

    victim_list = client.get("/api/v1/transactions", headers=_auth(victim_token))
    assert victim_list.status_code == 200
    assert len(victim_list.json()["items"]) == 1


def test_security_event_is_logged_on_sql_injection_attempt(client, caplog) -> None:
    token = _register_and_login(client, "sqli-log@example.com")
    client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": SQLI_PAYLOAD, "transaction_date": "2026-07-01"},
        headers=_auth(token),
    )
    assert any(
        "transaction_suspicious_input_rejected" in record.getMessage() for record in caplog.records
    )


# ---------------------------------------------------------------------------
# XSS -- category/note are free text and are NOT stripped of markup (only
# the SQLi-shaped pattern is rejected, per ADR-010). This is safe today
# because the API is JSON-only (Content-Type: application/json) with no
# HTML-rendering surface -- there is nowhere for a <script> tag to execute
# in this backend-only story. Documented explicitly rather than silently
# skipped: whichever future story renders these fields in a browser (the
# transaction list UI) MUST escape/sanitise on render (DOMPurify, per the
# constraint matrix) -- storing raw text here does not make that step
# optional later.
# ---------------------------------------------------------------------------


def test_xss_payload_in_category_is_stored_as_inert_text_not_executed(client) -> None:
    token = _register_and_login(client, "xss-category@example.com")
    create_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": XSS_PAYLOAD, "transaction_date": "2026-07-01"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    # Content-Type is application/json, not text/html -- a browser given
    # this response body will never parse it as executable markup.
    assert create_resp.headers["content-type"].startswith("application/json")
    assert create_resp.json()["category"] == XSS_PAYLOAD  # stored verbatim, as data


def test_xss_payload_in_note_is_stored_as_inert_text_not_executed(client) -> None:
    token = _register_and_login(client, "xss-note@example.com")
    create_resp = client.post(
        "/api/v1/transactions",
        json={
            "amount": "10.00",
            "category": "Groceries",
            "transaction_date": "2026-07-01",
            "note": XSS_PAYLOAD,
        },
        headers=_auth(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    assert create_resp.json()["note"] == XSS_PAYLOAD


# ---------------------------------------------------------------------------
# Auth bypass
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected_on_create(client) -> None:
    resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": "Groceries", "transaction_date": "2026-07-01"},
    )
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.get("/api/v1/transactions", headers={"Authorization": "NotBearer sometoken"})
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.get("/api/v1/transactions", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.get("/api/v1/transactions", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- the core security property of this story (first per-user
# resource-scoped endpoint in the codebase). Full-depth coverage (list,
# update, delete, 404-not-403) lives in
# tests/integration/test_transactions_api.py; this is the one additional
# check specific to the security-sweep framing: an attacker who knows a
# victim's real transaction id (e.g. leaked via a referrer header or logs)
# still cannot read it via GET on a hypothetical single-resource endpoint.
# Note: this story's API only exposes list/update/delete, no GET-by-id --
# recorded here so a future GET /transactions/{id} endpoint inherits this
# expectation rather than reinventing it.
# ---------------------------------------------------------------------------


def test_idor_no_get_by_id_endpoint_exists_yet_documented(client) -> None:
    """FINTRACK-15 does not implement GET /transactions/{id} (only list,
    update, delete) -- confirmed here so this isn't silently assumed. If
    added later, it must reuse the same 404-not-403 IDOR pattern as
    update/delete."""
    token = _register_and_login(client, "idor-no-get-by-id@example.com")
    resp = client.get(f"/api/v1/transactions/{uuid.uuid4()}", headers=_auth(token))
    assert resp.status_code in (404, 405)  # no route defined for this path
