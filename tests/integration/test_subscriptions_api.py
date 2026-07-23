"""QA Lead integration suite for FINTRACK-18 (Subscription / Recurring-
Charge Detection). Same approach as tests/integration/test_alerts_api.py:
hits the real FastAPI app over HTTP via TestClient, backed by a genuine
SQLite DB and fakeredis (see tests/conftest.py).

Every scenario in
tests/features/FINTRACK-18-subscription-detection.feature maps to a test
function below, plus gap-fill for re-detection (AC6), the AC5
not-re-suggested guarantee at the API level, confirm/mark-not-subscription
endpoints, auth, IDOR, and a large-dataset check.

Subscription detection is NOT a separate "run detection" endpoint --
per ADR-014's write-time-detection pattern (reused here from Alert/
FINTRACK-22), it runs as a best-effort side effect of
POST /api/v1/transactions. Every Gherkin "When subscription detection
runs" step below is therefore just "create the matching transaction(s)".
"""
from __future__ import annotations

import uuid


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


def _create_transaction(client, token: str, amount: str, transaction_date: str, note: str, category: str = "Bills"):
    resp = client.post(
        "/api/v1/transactions",
        json={"amount": amount, "category": category, "transaction_date": transaction_date, "note": note},
        headers=_auth(token),
    )
    assert resp.status_code == 201, resp.text
    return resp


def _list_subscriptions(client, token: str, include_dismissed: bool = False):
    params = {"include_dismissed": "true"} if include_dismissed else {}
    return client.get("/api/v1/subscriptions", headers=_auth(token), params=params)


def _confirm(client, token: str, subscription_id: str):
    return client.post(f"/api/v1/subscriptions/{subscription_id}/confirm", headers=_auth(token))


def _dismiss(client, token: str, subscription_id: str):
    return client.post(f"/api/v1/subscriptions/{subscription_id}/dismiss", headers=_auth(token))


def _mark_not_subscription(client, token: str, subscription_id: str):
    return client.post(f"/api/v1/subscriptions/{subscription_id}/mark-not-subscription", headers=_auth(token))


# ---------------------------------------------------------------------------
# Scenario 1: Three monthly charges from the same merchant are flagged
# ---------------------------------------------------------------------------


def test_three_monthly_netflix_charges_are_flagged_as_a_subscription(client) -> None:
    token = _register_and_login(client, "sub-netflix@example.com")
    _create_transaction(client, token, "15.99", "2026-01-01", "Netflix.com")
    _create_transaction(client, token, "15.99", "2026-01-31", "Netflix.com")
    _create_transaction(client, token, "15.99", "2026-03-02", "Netflix.com")

    items = _list_subscriptions(client, token).json()["items"]
    merchants = [s["merchant"] for s in items]
    assert "NETFLIX.COM" in merchants
    netflix = next(s for s in items if s["merchant"] == "NETFLIX.COM")
    assert netflix["status"] == "DETECTED"
    assert netflix["occurrences"] == 3


# ---------------------------------------------------------------------------
# Scenario 2: Irregular one-off charges are not flagged
# ---------------------------------------------------------------------------


def test_two_irregular_amazon_charges_are_not_flagged(client) -> None:
    token = _register_and_login(client, "sub-amazon@example.com")
    _create_transaction(client, token, "42.10", "2026-01-05", "AMAZON")
    _create_transaction(client, token, "9.99", "2026-04-20", "AMAZON")

    items = _list_subscriptions(client, token).json()["items"]
    assert "AMAZON" not in [s["merchant"] for s in items]


# ---------------------------------------------------------------------------
# Scenario 3: Subscription amount varies slightly within tolerance
# ---------------------------------------------------------------------------


def test_electric_co_amount_variance_within_tolerance_is_flagged(client) -> None:
    token = _register_and_login(client, "sub-electric@example.com")
    _create_transaction(client, token, "84.50", "2026-01-01", "ELECTRIC CO")
    _create_transaction(client, token, "91.20", "2026-01-31", "ELECTRIC CO")
    _create_transaction(client, token, "88.00", "2026-03-02", "ELECTRIC CO")

    items = _list_subscriptions(client, token).json()["items"]
    electric = next((s for s in items if s["merchant"] == "ELECTRIC CO"), None)
    assert electric is not None
    assert electric["amount_estimate"] == "87.90"


# ---------------------------------------------------------------------------
# Scenario 4: Malicious merchant string does not break detection
# ---------------------------------------------------------------------------


def test_malicious_merchant_string_is_returned_as_inert_json_text(client) -> None:
    """Backend-only repo -- there is no HTML-rendering surface here, so
    the "should be escaped/rendered as inert text, no script executes"
    requirement is satisfied by construction: the API returns the
    merchant as a JSON string field, never embedded in an HTML response.
    This test proves the payload survives detection unmodified as *data*
    and is never interpreted -- whichever future story renders this in a
    browser must still escape on render (DOMPurify, per the constraint
    matrix), same documented boundary as test_alerts_security.py's XSS
    coverage for Alert.category."""
    token = _register_and_login(client, "sub-xss@example.com")
    payload = "<script>alert(1)</script>"
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, token, "12.00", d, payload)

    resp = _list_subscriptions(client, token)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/json")
    merchants = [s["merchant"] for s in resp.json()["items"]]
    assert payload.upper() in merchants  # stored/returned verbatim, as data, never executed


# ---------------------------------------------------------------------------
# AC6 gap-fill: re-runs when new transactions are added
# ---------------------------------------------------------------------------


def test_a_fourth_transaction_refreshes_the_existing_subscription_not_a_duplicate(client) -> None:
    token = _register_and_login(client, "sub-rerun@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, token, "15.99", d, "Netflix.com")

    items_before = _list_subscriptions(client, token).json()["items"]
    assert len(items_before) == 1
    original_id = items_before[0]["id"]

    _create_transaction(client, token, "15.99", "2026-04-01", "Netflix.com")

    items_after = _list_subscriptions(client, token).json()["items"]
    assert len(items_after) == 1  # still one row, not a second
    assert items_after[0]["id"] == original_id
    assert items_after[0]["occurrences"] == 4


# ---------------------------------------------------------------------------
# AC5 gap-fill: dismissing at the API level suppresses future re-suggestion
# ---------------------------------------------------------------------------


def test_dismissing_a_subscription_prevents_it_reappearing_on_re_detection(client) -> None:
    token = _register_and_login(client, "sub-dismiss-then-rerun@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, token, "15.99", d, "Netflix.com")

    sub_id = _list_subscriptions(client, token).json()["items"][0]["id"]
    assert _dismiss(client, token, sub_id).status_code == 204
    assert _list_subscriptions(client, token).json()["items"] == []  # hidden by default

    # A further matching transaction must not resurrect it as DETECTED.
    _create_transaction(client, token, "15.99", "2026-04-01", "Netflix.com")
    assert _list_subscriptions(client, token).json()["items"] == []

    all_items = _list_subscriptions(client, token, include_dismissed=True).json()["items"]
    assert len(all_items) == 1
    assert all_items[0]["status"] == "DISMISSED"
    assert all_items[0]["occurrences"] == 3  # untouched by the 4th transaction


# ---------------------------------------------------------------------------
# AC3 gap-fill: confirm / mark-not-subscription endpoints
# ---------------------------------------------------------------------------


def test_confirm_endpoint_sets_status_confirmed(client) -> None:
    token = _register_and_login(client, "sub-confirm@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, token, "15.99", d, "Netflix.com")
    sub_id = _list_subscriptions(client, token).json()["items"][0]["id"]

    assert _confirm(client, token, sub_id).status_code == 204
    items = _list_subscriptions(client, token).json()["items"]
    assert items[0]["status"] == "CONFIRMED"


def test_mark_not_subscription_endpoint_sets_status_and_hides_it(client) -> None:
    token = _register_and_login(client, "sub-mark-not@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, token, "15.99", d, "Netflix.com")
    sub_id = _list_subscriptions(client, token).json()["items"][0]["id"]

    assert _mark_not_subscription(client, token, sub_id).status_code == 204
    assert _list_subscriptions(client, token).json()["items"] == []
    all_items = _list_subscriptions(client, token, include_dismissed=True).json()["items"]
    assert all_items[0]["status"] == "NOT_SUBSCRIPTION"


def test_confirming_a_nonexistent_subscription_returns_404(client) -> None:
    token = _register_and_login(client, "sub-confirm-missing@example.com")
    resp = _confirm(client, token, str(uuid.uuid4()))
    assert resp.status_code == 404


# ---------------------------------------------------------------------------
# Scoping gap-fill: subscriptions are per-user
# ---------------------------------------------------------------------------


def test_subscriptions_are_scoped_to_the_authenticated_user_only(client) -> None:
    user_a_token = _register_and_login(client, "sub-scope-a@example.com")
    user_b_token = _register_and_login(client, "sub-scope-b@example.com")

    for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
        _create_transaction(client, user_a_token, "15.99", d, "Netflix.com")

    a_items = _list_subscriptions(client, user_a_token).json()["items"]
    b_items = _list_subscriptions(client, user_b_token).json()["items"]
    assert len(a_items) == 1
    assert b_items == []


# ---------------------------------------------------------------------------
# Gap-fill: auth required on every endpoint
# ---------------------------------------------------------------------------


def test_all_subscription_endpoints_require_auth(client) -> None:
    assert client.get("/api/v1/subscriptions").status_code == 401
    assert client.post(f"/api/v1/subscriptions/{uuid.uuid4()}/confirm").status_code == 401
    assert client.post(f"/api/v1/subscriptions/{uuid.uuid4()}/dismiss").status_code == 401
    assert client.post(f"/api/v1/subscriptions/{uuid.uuid4()}/mark-not-subscription").status_code == 401


# ---------------------------------------------------------------------------
# Gap-fill: large dataset -- many independent merchant patterns for one
# user, list endpoint stays correct and user-scoped at scale.
# ---------------------------------------------------------------------------


def test_subscriptions_list_is_correct_across_many_independent_merchants(client) -> None:
    token = _register_and_login(client, "sub-large-dataset@example.com")
    for i in range(25):
        merchant = f"MERCHANT{i}.COM"
        for d in ("2026-01-01", "2026-01-31", "2026-03-02"):
            _create_transaction(client, token, "9.99", d, merchant)

    items = _list_subscriptions(client, token).json()["items"]
    assert len(items) == 25
    assert {s["merchant"] for s in items} == {f"MERCHANT{i}.COM" for i in range(25)}


# ---------------------------------------------------------------------------
# Gap-fill: concurrent-modification-shaped case -- several transactions
# for the same merchant landing back-to-back must still converge on a
# single row (unique constraint on (user_id, merchant) backs this at the
# DB layer; this test exercises the sequential path the constraint
# guards).
#
# CORRECTED (2026-07-23): this test originally used dates 14-16 days
# apart (avg gap ~15 days). detect_pattern() requires avg_gap within
# INTERVAL_TARGET_DAYS (30) +/- INTERVAL_TOLERANCE_DAYS (7) -- a ~15-day
# cadence is correctly rejected as "not monthly", so no subscription was
# ever created and the original assertion (len == 1) failed against 0,
# not because of a duplicate-row bug. Fixed to use ~30-day spacing so the
# test actually exercises "5 writes converge on one row" rather than
# "no pattern is ever detected in the first place".
# ---------------------------------------------------------------------------


def test_rapid_back_to_back_transactions_for_the_same_merchant_converge_on_one_row(client) -> None:
    token = _register_and_login(client, "sub-concurrent@example.com")
    for d in ("2026-01-01", "2026-01-31", "2026-03-02", "2026-04-01", "2026-05-01"):
        _create_transaction(client, token, "15.99", d, "Netflix.com")

    items = _list_subscriptions(client, token).json()["items"]
    netflix_rows = [s for s in items if s["merchant"] == "NETFLIX.COM"]
    assert len(netflix_rows) == 1  # never a duplicate row despite 5 rapid writes
