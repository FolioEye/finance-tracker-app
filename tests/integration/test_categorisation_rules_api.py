"""QA Lead integration suite for FINTRACK-17 (AI Auto-Categorisation Rules
Engine). Same approach as tests/integration/test_imports_api.py: hits the
real FastAPI app over HTTP via TestClient, backed by a genuine SQLite DB
and fakeredis (see tests/conftest.py).

Every scenario in tests/features/FINTRACK-17-auto-categorisation.feature
maps to a test function below.
"""
from __future__ import annotations

import uuid

import pytest


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


def _csv_bytes(*data_rows: str, header: str = "Date,Amount,Description,Category") -> bytes:
    return (header + "\n" + "\n".join(data_rows) + "\n").encode("utf-8")


def _create_rule(client, token: str, merchant_pattern: str, category: str):
    return client.post(
        "/api/v1/categorisation-rules",
        json={"merchant_pattern": merchant_pattern, "category": category},
        headers=_auth(token),
    )


def _stage(client, token: str, csv_bytes: bytes):
    return client.post(
        "/api/v1/imports", files={"file": ("statement.csv", csv_bytes, "text/csv")}, headers=_auth(token)
    )


# ---------------------------------------------------------------------------
# Scenario 1: Imported transaction auto-categorised from known merchant
# pattern
# ---------------------------------------------------------------------------


def test_imported_transaction_auto_categorised_from_known_merchant_pattern(client) -> None:
    token = _register_and_login(client, "catrule-known-merchant@example.com")
    rule_resp = _create_rule(client, token, "STARBUCKS", "Coffee & Dining")
    assert rule_resp.status_code == 201, rule_resp.text
    rule_id = rule_resp.json()["id"]

    stage_resp = _stage(
        client, token, _csv_bytes("2026-07-01,10.00,STARBUCKS #4521,")
    )
    assert stage_resp.status_code == 201, stage_resp.text
    row = stage_resp.json()["rows"][0]
    assert row["category"] == "Coffee & Dining"
    # AC6: auditable -- the review screen can see which rule produced the match.
    assert row["matched_rule_id"] == rule_id


# ---------------------------------------------------------------------------
# Scenario 2: Transaction from unknown merchant is flagged, not guessed
# ---------------------------------------------------------------------------


def test_transaction_from_unknown_merchant_is_flagged_uncategorised_not_guessed(client) -> None:
    token = _register_and_login(client, "catrule-unknown-merchant@example.com")
    # No rules created for this user at all.
    stage_resp = _stage(
        client, token, _csv_bytes("2026-07-01,10.00,XZQ HOLDINGS LLC,Some CSV Category")
    )
    assert stage_resp.status_code == 201, stage_resp.text
    row = stage_resp.json()["rows"][0]
    assert row["category"] == "Uncategorised"
    assert row["matched_rule_id"] is None


# ---------------------------------------------------------------------------
# Scenario 3: Bulk import of 200 transactions shows categorisation summary
# ---------------------------------------------------------------------------


def test_bulk_import_of_200_transactions_shows_categorisation_summary(client) -> None:
    token = _register_and_login(client, "catrule-bulk-200@example.com")
    _create_rule(client, token, "STARBUCKS", "Coffee & Dining")

    # Half match the rule, half don't.
    rows_text = []
    for i in range(200):
        merchant = "STARBUCKS #4521" if i % 2 == 0 else f"Unknown Merchant {i}"
        rows_text.append(f"2026-07-{(i % 28) + 1:02d},{i + 1}.00,{merchant},Food")
    stage_resp = _stage(client, token, _csv_bytes(*rows_text))
    assert stage_resp.status_code == 201, stage_resp.text
    body = stage_resp.json()
    assert body["found_count"] == 200
    assert body["auto_categorised_count"] == 100
    assert body["needs_review_count"] == 100

    uncategorised_rows = [r for r in body["rows"] if r["category"] == "Uncategorised"]
    assert len(uncategorised_rows) == 100


# ---------------------------------------------------------------------------
# Scenario 4: Attempt injection via a custom categorisation rule
# ---------------------------------------------------------------------------


def test_attempt_injection_via_custom_categorisation_rule_merchant_pattern(client) -> None:
    token = _register_and_login(client, "catrule-injection-merchant@example.com")
    resp = _create_rule(client, token, "'; DROP TABLE rules; --", "Groceries")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid characters detected"

    # The rules table remains intact -- no rule was created, so a later
    # import of that exact payload as a merchant string is not
    # auto-categorised by it.
    stage_resp = _stage(
        client, token, _csv_bytes("2026-07-01,10.00,'; DROP TABLE rules; --,Food")
    )
    assert stage_resp.status_code == 201, stage_resp.text
    assert stage_resp.json()["rows"][0]["matched_rule_id"] is None


def test_attempt_injection_via_custom_categorisation_rule_category(client) -> None:
    token = _register_and_login(client, "catrule-injection-category@example.com")
    resp = _create_rule(client, token, "Starbucks", "'; DROP TABLE rules; --")
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Invalid characters detected"


# ---------------------------------------------------------------------------
# Scenario 5: User's manual category correction updates their personal
# rule set
# ---------------------------------------------------------------------------


def test_manual_category_correction_creates_a_rule_and_future_imports_use_it(client) -> None:
    token = _register_and_login(client, "catrule-correction-feedback@example.com")

    # An imported transaction from an unknown merchant is left Uncategorised.
    stage_resp = _stage(client, token, _csv_bytes("2026-07-01,10.00,XZQ HOLDINGS LLC,"))
    import_id = stage_resp.json()["import_id"]
    commit_resp = client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(token))
    assert commit_resp.status_code == 200, commit_resp.text

    list_resp = client.get("/api/v1/transactions", headers=_auth(token))
    txn = list_resp.json()["items"][0]
    assert txn["category"] == "Uncategorised"
    assert txn["entry_source"] == "csv_import"

    # The user manually assigns it to a real category.
    correction_resp = client.patch(
        f"/api/v1/transactions/{txn['id']}",
        json={"category": "Business Expenses"},
        headers=_auth(token),
    )
    assert correction_resp.status_code == 200, correction_resp.text
    assert correction_resp.json()["category"] == "Business Expenses"

    # A future import from the same merchant is now auto-categorised.
    second_stage = _stage(
        client, token, _csv_bytes("2026-07-15,20.00,XZQ HOLDINGS LLC,")
    )
    assert second_stage.status_code == 201, second_stage.text
    row = second_stage.json()["rows"][0]
    assert row["category"] == "Business Expenses"
    assert row["matched_rule_id"] is not None


# ---------------------------------------------------------------------------
# Gap-fill: auth required
# ---------------------------------------------------------------------------


def test_create_categorisation_rule_without_auth_token_returns_401(client) -> None:
    resp = client.post(
        "/api/v1/categorisation-rules",
        json={"merchant_pattern": "Starbucks", "category": "Coffee & Dining"},
    )
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# Gap-fill: cross-user isolation (this story's IDOR-equivalent -- there's
# no GET/list/delete endpoint for a malicious user to directly query
# another user's rules against, so the risk here is a rule leaking across
# users during matching, not a direct read/write of another user's record)
# ---------------------------------------------------------------------------


def test_a_users_rule_does_not_auto_categorise_another_users_import(client) -> None:
    user_a_token = _register_and_login(client, "catrule-isolation-a@example.com")
    user_b_token = _register_and_login(client, "catrule-isolation-b@example.com")

    _create_rule(client, user_a_token, "STARBUCKS", "Coffee & Dining")

    stage_resp = _stage(
        client, user_b_token, _csv_bytes("2026-07-01,10.00,STARBUCKS #4521,")
    )
    assert stage_resp.status_code == 201, stage_resp.text
    row = stage_resp.json()["rows"][0]
    # User B has no rule of their own for this merchant, so it must NOT be
    # auto-categorised using user A's rule.
    assert row["category"] == "Uncategorised"
    assert row["matched_rule_id"] is None


def test_create_categorisation_rule_scoped_per_user_does_not_collide_on_same_pattern(client) -> None:
    user_a_token = _register_and_login(client, "catrule-scope-a@example.com")
    user_b_token = _register_and_login(client, "catrule-scope-b@example.com")

    resp_a = _create_rule(client, user_a_token, "STARBUCKS", "Coffee & Dining")
    resp_b = _create_rule(client, user_b_token, "STARBUCKS", "Business Expenses")
    assert resp_a.status_code == 201
    assert resp_b.status_code == 201
    assert resp_a.json()["id"] != resp_b.json()["id"]

    stage_a = _stage(client, user_a_token, _csv_bytes("2026-07-01,10.00,STARBUCKS #1,"))
    stage_b = _stage(client, user_b_token, _csv_bytes("2026-07-01,10.00,STARBUCKS #2,"))
    assert stage_a.json()["rows"][0]["category"] == "Coffee & Dining"
    assert stage_b.json()["rows"][0]["category"] == "Business Expenses"
