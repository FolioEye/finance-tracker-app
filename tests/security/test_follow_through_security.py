"""QA Lead mandatory security sweep for FINTRACK-23 (Action Follow-Through
Tracking), run at the real API level (TestClient -> real router -> real
Pydantic validation -> real handler -> real SQLite-backed repository).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on
every text input, auth bypass, IDOR. Structure matches
tests/security/test_alerts_security.py.

Narrow attack surface, same shape as alerts: there is no direct
create-record endpoint (a FollowThroughRecord is only ever created as a
side effect of GET /recommendations/weekly), so the only genuinely
user-controlled inputs are the record_id path parameter and the `action`
body field on POST /follow-through/{id}/actions.
"""
from __future__ import annotations

import uuid

SQLI_PAYLOAD = "'; DROP TABLE follow_through_records; --"
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


def _get_recommendation(client, token: str):
    return client.get("/api/v1/recommendations/weekly", headers=_auth(token))


def _record_action(client, token: str, record_id: str, action):
    return client.post(
        f"/api/v1/follow-through/{record_id}/actions", json={"action": action}, headers=_auth(token)
    )


# ---------------------------------------------------------------------------
# SQL injection
# ---------------------------------------------------------------------------


def test_sql_injection_shaped_record_id_path_param_rejected_as_malformed_uuid(client) -> None:
    """Mirrors test_alerts_security.py's equivalent test: FastAPI's UUID
    path-type validation rejects this before it ever reaches application
    code or a query -- a clean 422, never a 500 or a raw traceback."""
    token = _register_and_login(client, "ft23-sqli-path@example.com")
    resp = _record_action(client, token, SQLI_PAYLOAD, "done")
    assert resp.status_code == 422
    assert resp.headers["content-type"].startswith("application/json")
    assert resp.json()["detail"][0]["type"] == "uuid_parsing"


def test_sql_injection_shaped_action_value_is_rejected_by_application_validation_not_a_query(client) -> None:
    """`action` never reaches a query at all -- RecordRecommendationActionHandler
    checks it against a fixed allow-list (VALID_ACTIONS) before any
    repository call. A SQLi-shaped string is just another invalid value,
    rejected the same way "delete" is in the Gherkin's negative scenario."""
    token = _register_and_login(client, "ft23-sqli-action@example.com")
    rec = _get_recommendation(client, token)
    record_id = rec.json()["follow_through_record_id"]

    resp = _record_action(client, token, record_id, SQLI_PAYLOAD)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid action value"

    # A real, unrelated user's own record surviving right after is the
    # strongest evidence no query was ever built from the payload.
    other_token = _register_and_login(client, "ft23-sqli-bystander@example.com")
    other_rec = _get_recommendation(client, other_token)
    assert other_rec.status_code == 200


# ---------------------------------------------------------------------------
# XSS -- `action` is validated against a fixed allow-list, never reflected
# or stored verbatim, so there's no injection surface on this router at
# all (unlike alerts.category, which is free text inherited from another
# entity). This test documents that absence rather than skipping it.
# ---------------------------------------------------------------------------


def test_xss_payload_in_action_is_rejected_as_an_invalid_action_never_stored_or_reflected(client) -> None:
    token = _register_and_login(client, "ft23-xss-action@example.com")
    rec = _get_recommendation(client, token)
    record_id = rec.json()["follow_through_record_id"]

    resp = _record_action(client, token, record_id, XSS_PAYLOAD)
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid action value"
    assert XSS_PAYLOAD not in resp.text  # never reflected back


# ---------------------------------------------------------------------------
# Auth bypass -- all three follow-through endpoints
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected_on_actions(client) -> None:
    resp = client.post(f"/api/v1/follow-through/{uuid.uuid4()}/actions", json={"action": "done"})
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_missing_token_rejected_on_history(client) -> None:
    resp = client.get("/api/v1/follow-through")
    assert resp.status_code == 401


def test_auth_bypass_missing_token_rejected_on_rate(client) -> None:
    resp = client.get("/api/v1/follow-through/rate")
    assert resp.status_code == 401


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.get("/api/v1/follow-through", headers={"Authorization": "NotBearer sometoken"})
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.get("/api/v1/follow-through", headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.get("/api/v1/follow-through", headers={"Authorization": f"Bearer {forged}"})
    assert resp.status_code == 401


def test_auth_bypass_expired_token_rejected_on_actions(client) -> None:
    import jwt as pyjwt

    from apps.api.config import get_settings

    settings = get_settings()
    expired = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4()), "exp": 1},
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )
    resp = client.post(
        f"/api/v1/follow-through/{uuid.uuid4()}/actions",
        json={"action": "done"},
        headers={"Authorization": f"Bearer {expired}"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR
# ---------------------------------------------------------------------------


def test_idor_cannot_mark_another_users_record_done(client) -> None:
    victim_token = _register_and_login(client, "ft23-idor-sec-victim@example.com")
    attacker_token = _register_and_login(client, "ft23-idor-sec-attacker@example.com")
    victim_record_id = _get_recommendation(client, victim_token).json()["follow_through_record_id"]

    resp = _record_action(client, attacker_token, victim_record_id, "done")
    assert resp.status_code == 404  # not 403 -- can't be used to confirm the id exists


def test_idor_history_never_leaks_another_users_records(client) -> None:
    victim_token = _register_and_login(client, "ft23-idor-sec-list-victim@example.com")
    attacker_token = _register_and_login(client, "ft23-idor-sec-list-attacker@example.com")
    _get_recommendation(client, victim_token)

    attacker_items = client.get("/api/v1/follow-through", headers=_auth(attacker_token)).json()["items"]
    assert attacker_items == []


def test_idor_a_forged_record_id_belonging_to_no_one_returns_404_not_500(client) -> None:
    token = _register_and_login(client, "ft23-idor-sec-forged@example.com")
    resp = _record_action(client, token, str(uuid.uuid4()), "done")
    assert resp.status_code == 404


def test_idor_rate_is_computed_only_from_the_callers_own_records(client) -> None:
    victim_token = _register_and_login(client, "ft23-idor-sec-rate-victim@example.com")
    attacker_token = _register_and_login(client, "ft23-idor-sec-rate-attacker@example.com")

    victim_record_id = _get_recommendation(client, victim_token).json()["follow_through_record_id"]
    _record_action(client, victim_token, victim_record_id, "done")

    attacker_rate = client.get("/api/v1/follow-through/rate", headers=_auth(attacker_token)).json()
    assert attacker_rate["done_count"] == 0
