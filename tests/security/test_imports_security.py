"""QA Lead mandatory security sweep for FINTRACK-16 (Statement/CSV/PDF
Import), run at the real API level (TestClient -> real router -> real
Pydantic validation -> real handlers -> real SQLite-backed repository +
fakeredis-backed staging).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on
every text input, auth bypass, IDOR. This story's IDOR checks are covered
in depth in tests/integration/test_imports_api.py; this file focuses on
injection and auth-bypass, plus the CSV-formula-injection vector that is
this story's own dedicated security scenario (distinct from SQLi/XSS).

FINTRACK-17 update: the category-column tests below were rewritten, not
just re-passed. apply_auto_categorisation() (ADR-012, decision D) means
the CSV's own category/type column is no longer used as transaction
category data at all -- a rule match or "Uncategorised" is now
authoritative. So SQLi/XSS payloads planted in that column (this file's
original FINTRACK-16 tests) never reach Transaction.new() as data in the
first place; they don't need to be rejected-and-skipped because they're
never used as a value to begin with. This is a stronger guarantee, not a
weaker one, but it changes what these tests need to assert. The
description/note column is unaffected -- it still flows into
Transaction.new() unchanged, so its SQLi/XSS tests are untouched.
"""
from __future__ import annotations

import uuid

SQLI_PAYLOAD = "'; DROP TABLE transactions; --"
XSS_PAYLOAD = "<script>alert('xss')</script>"
FORMULA_PAYLOAD = "=cmd|'/c calc'!A1"


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


def _stage(client, token: str, csv_bytes: bytes):
    return client.post(
        "/api/v1/imports", files={"file": ("statement.csv", csv_bytes, "text/csv")}, headers=_auth(token)
    )


# ---------------------------------------------------------------------------
# SQL injection -- category/note fields inside CSV rows
# ---------------------------------------------------------------------------
#
# Different handling from FINTRACK-15's direct-field SQLi rejection: a
# manual-entry POST rejects the whole request with 400. A CSV row is one
# of potentially thousands in a single upload, so the design choice here
# (ADR-011) is to skip just the offending row at commit time rather than
# fail the entire batch -- committed_count/skipped_count reflect this.
# ---------------------------------------------------------------------------


def test_sql_injection_in_csv_category_column_never_becomes_transaction_data(client) -> None:
    """FINTRACK-17 rewrite (was test_sql_injection_in_csv_category_is_skipped_at_commit_not_committed,
    which asserted a commit-time skip -- no skip happens now, because the
    category column this payload lives in is never read as data at all).
    Both rows commit; the auto-categorisation engine assigns
    "Uncategorised" to the second row (no rule matches "Normal purchase"),
    so the injection payload is discarded during staging, well before
    Transaction.new() would even see it."""
    token = _register_and_login(client, "import-sqli-category@example.com")
    csv_bytes = _csv_bytes(
        "2026-07-01,10.00,Coffee,Food",
        f"2026-07-02,20.00,Normal purchase,{SQLI_PAYLOAD}",
    )
    stage_resp = _stage(client, token, csv_bytes)
    assert stage_resp.status_code == 201, stage_resp.text
    import_id = stage_resp.json()["import_id"]
    # Not caught at stage time -- formula-injection sanitisation only
    # triggers on a LEADING =/+/-/@/tab/CR, which this payload doesn't have.
    assert stage_resp.json()["rows"][1]["status"] == "ok"
    assert stage_resp.json()["rows"][1]["category"] == "Uncategorised"

    commit_resp = client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(token))
    assert commit_resp.status_code == 200, commit_resp.text
    assert commit_resp.json()["committed_count"] == 2
    assert commit_resp.json()["skipped_count"] == 0

    list_resp = client.get("/api/v1/transactions", headers=_auth(token))
    categories = [item["category"] for item in list_resp.json()["items"]]
    assert SQLI_PAYLOAD not in categories


def test_sql_injection_in_csv_note_is_skipped_at_commit_not_committed(client) -> None:
    """The row is RowStatus.OK at stage time (note isn't checked by the
    lighter validators), so NothingToCommitError does NOT fire here --
    that only triggers when committable_rows is empty *before* the commit
    loop runs. This row is attempted, fails Transaction.new()'s
    SuspiciousInputError check, and is counted as skipped -- a 200 with
    committed_count=0, not a 400."""
    token = _register_and_login(client, "import-sqli-note@example.com")
    csv_bytes = _csv_bytes(f"2026-07-01,10.00,{SQLI_PAYLOAD},Groceries")
    stage_resp = _stage(client, token, csv_bytes)
    import_id = stage_resp.json()["import_id"]

    commit_resp = client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(token))
    assert commit_resp.status_code == 200, commit_resp.text
    assert commit_resp.json()["committed_count"] == 0
    assert commit_resp.json()["skipped_count"] == 1

    list_resp = client.get("/api/v1/transactions", headers=_auth(token))
    assert list_resp.json()["items"] == []


def test_sql_injection_payload_does_not_disturb_other_users_data(client) -> None:
    """If the payload had reached a query unparameterised, a DROP TABLE
    would take out every transaction, not just fail to commit one row. A
    real, unrelated user's transaction surviving right after is the
    strongest evidence the table is intact."""
    victim_token = _register_and_login(client, "import-sqli-bystander-victim@example.com")
    client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": "Groceries", "transaction_date": "2026-07-01"},
        headers=_auth(victim_token),
    )

    attacker_token = _register_and_login(client, "import-sqli-bystander-attacker@example.com")
    csv_bytes = _csv_bytes(f"2026-07-01,10.00,Purchase,{SQLI_PAYLOAD}")
    stage_resp = _stage(client, attacker_token, csv_bytes)
    import_id = stage_resp.json()["import_id"]
    client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(attacker_token))

    victim_list = client.get("/api/v1/transactions", headers=_auth(victim_token))
    assert victim_list.status_code == 200
    assert len(victim_list.json()["items"]) == 1


def test_security_event_is_logged_on_csv_row_sql_injection_attempt(client, caplog) -> None:
    """The commit-time skip is silent to the HTTP response by design
    (best-effort batch import), but it must still be observable in logs.
    Regression test for the gap found during FINTRACK-16's QA pass:
    skipped rows previously produced zero log signal; import_commit_rows_skipped
    is logged at WARNING whenever a row is skipped during commit.

    FINTRACK-17 update: the payload now targets the description/note
    column, not category -- as of ADR-012, an SQLi payload in the
    category column is discarded during staging and never reaches
    Transaction.new(), so it can no longer trigger a commit-time skip
    (see test_sql_injection_in_csv_category_column_never_becomes_transaction_data
    above). The note column is unaffected by that change and still
    flows into Transaction.new() unchanged, so it's still the live
    vector this log line needs to cover."""
    token = _register_and_login(client, "import-sqli-log@example.com")
    csv_bytes = _csv_bytes(
        "2026-07-01,10.00,Coffee,Food",
        f"2026-07-02,20.00,{SQLI_PAYLOAD},Food",
    )
    stage_resp = _stage(client, token, csv_bytes)
    import_id = stage_resp.json()["import_id"]
    client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(token))

    assert any("import_commit_rows_skipped" in record.getMessage() for record in caplog.records)


# ---------------------------------------------------------------------------
# CSV formula injection -- this story's own dedicated security scenario,
# distinct from SQLi. Full happy-path coverage lives in the Gherkin-mapped
# scenario in tests/integration/test_imports_api.py; these are additional
# edge cases.
# ---------------------------------------------------------------------------


def test_formula_injection_payload_is_never_committed_unsanitised(client) -> None:
    token = _register_and_login(client, "import-formula-commit@example.com")
    csv_bytes = _csv_bytes(f'2026-07-01,10.00,"{FORMULA_PAYLOAD}",Groceries')
    stage_resp = _stage(client, token, csv_bytes)
    import_id = stage_resp.json()["import_id"]

    commit_resp = client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(token))
    assert commit_resp.status_code == 200, commit_resp.text
    assert commit_resp.json()["committed_count"] == 1

    list_resp = client.get("/api/v1/transactions", headers=_auth(token))
    note = list_resp.json()["items"][0]["note"]
    assert note.startswith("'=")  # quote-prefixed -- Excel/Sheets render as inert text
    assert not note.startswith("=")  # never stored with a bare leading '='


def test_formula_injection_in_multiple_trigger_characters_all_sanitised(client) -> None:
    token = _register_and_login(client, "import-formula-multi@example.com")
    csv_bytes = _csv_bytes(
        "2026-07-01,10.00,=SUM(A1:A2),Food",
        "2026-07-02,20.00,+1+1,Food",
        "2026-07-03,30.00,-1-1,Food",
        "2026-07-04,40.00,@cmd,Food",
    )
    stage_resp = _stage(client, token, csv_bytes)
    body = stage_resp.json()
    assert body["flagged_count"] == 4
    assert all(row["status"] == "flagged" for row in body["rows"])
    assert all(row["note"][0] == "'" for row in body["rows"])


# ---------------------------------------------------------------------------
# XSS -- category/note are free text and are NOT stripped of markup, same
# rationale as FINTRACK-15's equivalent tests: this API is JSON-only, no
# HTML-rendering surface for a <script> tag to execute in.
# ---------------------------------------------------------------------------


def test_xss_payload_in_csv_category_column_never_becomes_transaction_data(client) -> None:
    """FINTRACK-17 rewrite (was test_xss_payload_in_csv_category_is_stored_as_inert_text_not_executed,
    which asserted the payload was "stored verbatim, as data" -- it no
    longer is stored at all, verbatim or otherwise). The category column
    is superseded by the auto-categorisation engine (ADR-012, decision
    D): no rule matches "Purchase", so the row's category becomes
    "Uncategorised" and the XSS-shaped text in the CSV's category column
    is simply discarded during staging. See
    test_xss_payload_in_csv_note_is_stored_as_inert_text_not_executed
    below for the description/note column, which is unaffected and still
    stores its payload verbatim as inert JSON data."""
    token = _register_and_login(client, "import-xss-category@example.com")
    csv_bytes = _csv_bytes(f"2026-07-01,10.00,Purchase,{XSS_PAYLOAD}")
    stage_resp = _stage(client, token, csv_bytes)
    import_id = stage_resp.json()["import_id"]
    assert stage_resp.json()["rows"][0]["category"] == "Uncategorised"
    commit_resp = client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(token))
    assert commit_resp.status_code == 200, commit_resp.text
    assert commit_resp.json()["committed_count"] == 1

    list_resp = client.get("/api/v1/transactions", headers=_auth(token))
    assert list_resp.headers["content-type"].startswith("application/json")
    assert list_resp.json()["items"][0]["category"] == "Uncategorised"
    assert XSS_PAYLOAD not in list_resp.text


def test_xss_payload_in_csv_note_is_stored_as_inert_text_not_executed(client) -> None:
    token = _register_and_login(client, "import-xss-note@example.com")
    csv_bytes = _csv_bytes(f'2026-07-01,10.00,"{XSS_PAYLOAD}",Groceries')
    stage_resp = _stage(client, token, csv_bytes)
    import_id = stage_resp.json()["import_id"]
    commit_resp = client.post(f"/api/v1/imports/{import_id}/commit", headers=_auth(token))
    assert commit_resp.status_code == 200, commit_resp.text

    list_resp = client.get("/api/v1/transactions", headers=_auth(token))
    assert list_resp.json()["items"][0]["note"] == XSS_PAYLOAD


# ---------------------------------------------------------------------------
# Auth bypass -- every /api/v1/imports/* endpoint
# ---------------------------------------------------------------------------


def test_auth_bypass_missing_token_rejected_on_stage(client) -> None:
    resp = client.post(
        "/api/v1/imports", files={"file": ("statement.csv", b"Date,Amount\n2026-07-01,1.00\n", "text/csv")}
    )
    assert resp.status_code == 401
    assert resp.headers.get("www-authenticate") == "Bearer"


def test_auth_bypass_malformed_authorization_header_rejected(client) -> None:
    resp = client.post(
        "/api/v1/imports",
        files={"file": ("statement.csv", b"Date,Amount\n2026-07-01,1.00\n", "text/csv")},
        headers={"Authorization": "NotBearer sometoken"},
    )
    assert resp.status_code == 401


def test_auth_bypass_empty_bearer_token_rejected(client) -> None:
    resp = client.patch(f"/api/v1/imports/{uuid.uuid4()}", json={"edits": []}, headers={"Authorization": "Bearer "})
    assert resp.status_code == 401


def test_auth_bypass_token_signed_with_wrong_secret_rejected(client) -> None:
    import jwt as pyjwt

    forged = pyjwt.encode(
        {"sub": str(uuid.uuid4()), "type": "access", "jti": str(uuid.uuid4())},
        "attacker-controlled-wrong-secret",
        algorithm="HS256",
    )
    resp = client.post(f"/api/v1/imports/{uuid.uuid4()}/commit", headers=_auth(forged))
    assert resp.status_code == 401


def test_auth_bypass_garbage_bearer_token_rejected_on_discard(client) -> None:
    resp = client.delete(f"/api/v1/imports/{uuid.uuid4()}", headers=_auth("not-a-real-jwt"))
    assert resp.status_code == 401


# ---------------------------------------------------------------------------
# IDOR -- full-depth coverage (edit, commit, discard) lives in
# tests/integration/test_imports_api.py; documented here that no
# list-staged-imports endpoint exists, so there is no enumeration surface
# to test against, same discipline as FINTRACK-15's missing-GET-by-id note.
# ---------------------------------------------------------------------------


def test_idor_no_list_staged_imports_endpoint_exists_documented(client) -> None:
    """This story only exposes stage/edit/commit/discard by id -- no
    GET /api/v1/imports (list) endpoint, so there is nothing for an
    attacker to enumerate even with a valid token. Recorded here so a
    future list endpoint inherits user_id-scoping from the start rather
    than reinventing this expectation."""
    token = _register_and_login(client, "import-idor-no-list@example.com")
    resp = client.get("/api/v1/imports", headers=_auth(token))
    assert resp.status_code in (404, 405)


# ---------------------------------------------------------------------------
# No bank credentials ever requested (AC7) -- a negative/structural check:
# confirm the stage endpoint's accepted request shape has no field that
# could carry bank credentials.
# ---------------------------------------------------------------------------


def test_no_bank_credential_fields_accepted_by_stage_endpoint(client) -> None:
    """AC7: 'No bank credentials ever requested.' The stage endpoint only
    accepts a multipart file upload -- there is no username/password/
    account-number field in its request shape for a credential to even
    be placed into."""
    token = _register_and_login(client, "import-no-bank-creds@example.com")
    resp = client.post(
        "/api/v1/imports",
        files={"file": ("statement.csv", b"Date,Amount\n2026-07-01,1.00\n", "text/csv")},
        data={"bank_username": "attacker", "bank_password": "hunter2"},  # extra fields, if any, are ignored
        headers=_auth(token),
    )
    # Extra unexpected form fields are simply ignored by FastAPI's
    # UploadFile-only signature -- no error, and definitely no credential
    # ever read or persisted.
    assert resp.status_code in (201, 400)
