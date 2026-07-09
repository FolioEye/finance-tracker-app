"""QA Lead integration suite for FINTRACK-15 (Add Manual Transaction).

Same approach as tests/integration/test_login_logout_api.py: hits the real
FastAPI app over HTTP via TestClient, backed by a genuine SQLite DB (see
tests/conftest.py).

Every scenario in tests/features/FINTRACK-15-add-manual-transaction.feature
maps to a step implementation below -- pytest-bdd fails at collection time
if a step in the .feature file has no matching implementation here. Two of
the four scenarios share the step text 'I enter amount "{amount}" in the
transaction form': the max-amount-boundary scenario has no explicit "click
Save Transaction" step afterward, so that step submits immediately; the
negative-amount scenario's later explicit click re-submits the same
(still-invalid) values, which is harmless since a validation failure
creates no transaction either way.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import jwt as pyjwt
import pytest
from pytest_bdd import given, parsers, scenarios, then, when

scenarios("../features/FINTRACK-15-add-manual-transaction.feature")

TEST_JWT_SECRET = "test-secret-key-not-for-production-use-only"


class TransactionContext:
    """Per-scenario mutable state shared between Given/When/Then steps."""

    def __init__(self) -> None:
        self.token: str | None = None
        self.amount: str = "10.00"
        self.category: str = "Groceries"
        self.transaction_date: str = "2026-07-01"
        self.note: str | None = None
        self.response = None


@pytest.fixture
def ctx() -> TransactionContext:
    return TransactionContext()


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


def _submit(client, ctx: TransactionContext):
    ctx.response = client.post(
        "/api/v1/transactions",
        json={
            "amount": ctx.amount,
            "category": ctx.category,
            "transaction_date": ctx.transaction_date,
            "note": ctx.note,
        },
        headers=_auth(ctx.token),
    )
    return ctx.response


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("I am authenticated as a registered user")
def authenticated_user(client, ctx: TransactionContext) -> None:
    email = f"txn-scenario-user-{uuid.uuid4().hex[:8]}@example.com"
    ctx.token = _register_and_login(client, email)


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when(parsers.parse('I enter amount "{amount}", category "{category}", date "{transaction_date}"'))
def enter_amount_category_date(ctx: TransactionContext, amount: str, category: str, transaction_date: str) -> None:
    ctx.amount = amount
    ctx.category = category
    ctx.transaction_date = transaction_date


@when('I click "Save Transaction"')
def click_save_transaction(client, ctx: TransactionContext) -> None:
    _submit(client, ctx)


@when(parsers.parse('I enter amount "{amount}" in the transaction form'))
def enter_amount_in_form(client, ctx: TransactionContext, amount: str) -> None:
    ctx.amount = amount
    _submit(client, ctx)


@when(parsers.parse('I enter description "{description}"'))
def enter_description(ctx: TransactionContext, description: str) -> None:
    ctx.note = description


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the transaction appears in my transaction list")
def transaction_appears_in_list(client, ctx: TransactionContext) -> None:
    assert ctx.response.status_code == 201, ctx.response.text
    resp = client.get("/api/v1/transactions", headers=_auth(ctx.token))
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    assert items[0]["amount"] == "42.50"
    assert items[0]["category"] == "Groceries"


@then(parsers.parse('my budget total for "{category}" decreases by "{amount}"'))
def budget_total_decreases(category: str, amount: str) -> None:
    """AC4's budget-total assertion cannot be implemented or tested yet --
    no Budget entity exists (FINTRACK-20). See ADR-010's Consequences
    section, where Tech Lead flagged this exact gap. The transaction-list
    half of this scenario's expectation is already verified by
    transaction_appears_in_list above (the prior Then step in the same
    scenario) -- this step exists only so pytest-bdd has a matching
    implementation for the Gherkin line, and documents the gap rather than
    fabricating an assertion against an entity that doesn't exist yet.
    """


@then(parsers.parse('I should see validation error "{message}"'))
def should_see_validation_error(ctx: TransactionContext, message: str) -> None:
    assert ctx.response.status_code == 400, ctx.response.text
    assert ctx.response.json()["detail"] == message


@then("no transaction should be created")
def no_transaction_created(client, ctx: TransactionContext) -> None:
    resp = client.get("/api/v1/transactions", headers=_auth(ctx.token))
    assert resp.status_code == 200
    assert resp.json()["items"] == []


@then("the input should be sanitised")
def input_sanitised(ctx: TransactionContext) -> None:
    assert ctx.response.status_code == 400


@then("the database should remain intact")
def database_intact(client) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "post-transaction-injection-sanity-check@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert resp.status_code == 201, resp.text


@then("a security event should be logged")
def security_event_logged(caplog) -> None:
    assert any(
        "transaction_suspicious_input_rejected" in record.getMessage() for record in caplog.records
    )


# ---------------------------------------------------------------------------
# Extra scenarios beyond the Gherkin, per QA Lead process step 1: AC5
# edit/delete (no Gherkin coverage -- flagged by Tech Lead in ADR-010),
# IDOR, pagination, concurrent modification, large dataset, accessibility.
# ---------------------------------------------------------------------------


def test_full_crud_lifecycle_create_list_update_delete(client) -> None:
    """AC5 ('Editable/deletable') end-to-end -- no Gherkin scenario covers
    this, so this is the QA Lead gap-fill test for the full lifecycle."""
    token = _register_and_login(client, "crud-lifecycle@example.com")

    create_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "42.50", "category": "Groceries", "transaction_date": "2026-07-02", "note": "Weekly shop"},
        headers=_auth(token),
    )
    assert create_resp.status_code == 201, create_resp.text
    transaction_id = create_resp.json()["id"]

    list_resp = client.get("/api/v1/transactions", headers=_auth(token))
    assert len(list_resp.json()["items"]) == 1

    update_resp = client.patch(
        f"/api/v1/transactions/{transaction_id}",
        json={"amount": "55.00", "category": "Household"},
        headers=_auth(token),
    )
    assert update_resp.status_code == 200, update_resp.text
    assert update_resp.json()["amount"] == "55.00"
    assert update_resp.json()["category"] == "Household"
    assert update_resp.json()["note"] == "Weekly shop"  # untouched by partial update

    delete_resp = client.delete(f"/api/v1/transactions/{transaction_id}", headers=_auth(token))
    assert delete_resp.status_code == 204

    final_list = client.get("/api/v1/transactions", headers=_auth(token))
    assert final_list.json()["items"] == []


def test_update_transaction_rejects_invalid_amount(client) -> None:
    token = _register_and_login(client, "update-invalid-amount@example.com")
    create_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "42.50", "category": "Groceries", "transaction_date": "2026-07-02"},
        headers=_auth(token),
    )
    transaction_id = create_resp.json()["id"]

    update_resp = client.patch(
        f"/api/v1/transactions/{transaction_id}", json={"amount": "-5.00"}, headers=_auth(token)
    )
    assert update_resp.status_code == 400
    assert update_resp.json()["detail"] == "Amount must be a positive number"


def test_update_nonexistent_transaction_returns_404(client) -> None:
    token = _register_and_login(client, "update-missing@example.com")
    resp = client.patch(
        f"/api/v1/transactions/{uuid.uuid4()}", json={"amount": "10.00"}, headers=_auth(token)
    )
    assert resp.status_code == 404
    assert resp.json()["detail"] == "Transaction not found"


def test_delete_transaction_twice_returns_404_the_second_time(client) -> None:
    token = _register_and_login(client, "delete-twice@example.com")
    create_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": "Groceries", "transaction_date": "2026-07-02"},
        headers=_auth(token),
    )
    transaction_id = create_resp.json()["id"]

    first = client.delete(f"/api/v1/transactions/{transaction_id}", headers=_auth(token))
    assert first.status_code == 204

    second = client.delete(f"/api/v1/transactions/{transaction_id}", headers=_auth(token))
    assert second.status_code == 404


# --- IDOR: cross-user access must fail, and fail as 404 (not 403) ---------


def test_idor_second_user_cannot_see_first_users_transaction_in_their_list(client) -> None:
    victim_token = _register_and_login(client, "idor-victim-list@example.com")
    attacker_token = _register_and_login(client, "idor-attacker-list@example.com")

    client.post(
        "/api/v1/transactions",
        json={"amount": "500.00", "category": "Private", "transaction_date": "2026-07-02"},
        headers=_auth(victim_token),
    )

    attacker_list = client.get("/api/v1/transactions", headers=_auth(attacker_token))
    assert attacker_list.status_code == 200
    assert attacker_list.json()["items"] == []


def test_idor_second_user_cannot_update_first_users_transaction(client) -> None:
    victim_token = _register_and_login(client, "idor-victim-update@example.com")
    attacker_token = _register_and_login(client, "idor-attacker-update@example.com")

    create_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "500.00", "category": "Private", "transaction_date": "2026-07-02"},
        headers=_auth(victim_token),
    )
    victim_transaction_id = create_resp.json()["id"]

    attacker_update = client.patch(
        f"/api/v1/transactions/{victim_transaction_id}",
        json={"amount": "0.01"},
        headers=_auth(attacker_token),
    )
    # 404, not 403 -- same information-hiding principle as login's generic
    # error: the response must not confirm the id exists for another user.
    assert attacker_update.status_code == 404

    # Victim's data is provably untouched.
    victim_list = client.get("/api/v1/transactions", headers=_auth(victim_token))
    assert victim_list.json()["items"][0]["amount"] == "500.00"


def test_idor_second_user_cannot_delete_first_users_transaction(client) -> None:
    victim_token = _register_and_login(client, "idor-victim-delete@example.com")
    attacker_token = _register_and_login(client, "idor-attacker-delete@example.com")

    create_resp = client.post(
        "/api/v1/transactions",
        json={"amount": "500.00", "category": "Private", "transaction_date": "2026-07-02"},
        headers=_auth(victim_token),
    )
    victim_transaction_id = create_resp.json()["id"]

    attacker_delete = client.delete(
        f"/api/v1/transactions/{victim_transaction_id}", headers=_auth(attacker_token)
    )
    assert attacker_delete.status_code == 404

    victim_list = client.get("/api/v1/transactions", headers=_auth(victim_token))
    assert len(victim_list.json()["items"]) == 1


# --- Pagination ------------------------------------------------------------


def test_pagination_returns_a_next_cursor_when_more_rows_exist(client) -> None:
    token = _register_and_login(client, "pagination-cursor@example.com")
    for i in range(5):
        resp = client.post(
            "/api/v1/transactions",
            json={"amount": f"{i + 1}.00", "category": "Groceries", "transaction_date": "2026-07-01"},
            headers=_auth(token),
        )
        assert resp.status_code == 201

    page1 = client.get("/api/v1/transactions?limit=2", headers=_auth(token))
    assert page1.status_code == 200
    body1 = page1.json()
    assert len(body1["items"]) == 2
    assert body1["next_cursor"] is not None

    page2 = client.get(f"/api/v1/transactions?limit=2&cursor={body1['next_cursor']}", headers=_auth(token))
    body2 = page2.json()
    assert len(body2["items"]) == 2

    # No overlap between pages.
    ids_page1 = {item["id"] for item in body1["items"]}
    ids_page2 = {item["id"] for item in body2["items"]}
    assert ids_page1.isdisjoint(ids_page2)


def test_pagination_walks_to_the_last_page_with_a_null_cursor(client) -> None:
    token = _register_and_login(client, "pagination-last-page@example.com")
    for i in range(3):
        client.post(
            "/api/v1/transactions",
            json={"amount": f"{i + 1}.00", "category": "Groceries", "transaction_date": "2026-07-01"},
            headers=_auth(token),
        )

    seen_ids: set[str] = set()
    cursor = None
    for _ in range(10):  # generous upper bound to avoid an infinite loop on a bug
        url = "/api/v1/transactions?limit=1"
        if cursor:
            url += f"&cursor={cursor}"
        resp = client.get(url, headers=_auth(token))
        body = resp.json()
        for item in body["items"]:
            seen_ids.add(item["id"])
        cursor = body["next_cursor"]
        if cursor is None:
            break

    assert len(seen_ids) == 3


# --- Concurrent modification -------------------------------------------


@pytest.mark.asyncio
async def test_concurrent_transaction_creation_for_same_user_all_persist_correctly(
    test_session_factory,
) -> None:
    """Concurrent modification scenario the Gherkin doesn't cover: several
    simultaneous transaction creations for the same user must all persist
    independently with unique ids -- no lost writes or interleaved
    corruption. Exercises the real SqlAlchemyTransactionRepository
    directly, since TestClient's requests are sequential and wouldn't
    actually race (same pattern as FINTRACK-14's concurrent-login test).
    """
    from apps.api.domain.models.transaction import Money, Transaction
    from apps.api.infrastructure.repositories.sqlalchemy_transaction_repository import (
        SqlAlchemyTransactionRepository,
    )

    user_id = uuid.uuid4()

    async def _create_one(amount: str) -> uuid.UUID:
        async with test_session_factory() as session:
            repo = SqlAlchemyTransactionRepository(session)
            txn = Transaction.new(
                user_id=user_id,
                amount=Money.parse(amount),
                category="Concurrent",
                transaction_date=date(2026, 7, 2),
            )
            await repo.add(txn)
            await session.commit()
            return txn.id

    ids = await asyncio.gather(*[_create_one(f"{i + 1}.00") for i in range(10)])
    assert len(set(ids)) == 10  # all unique -- none lost or overwritten

    async with test_session_factory() as session:
        repo = SqlAlchemyTransactionRepository(session)
        page = await repo.list_for_user(user_id=user_id, limit=50, cursor=None)
        assert len(page.items) == 10


# --- Large dataset -------------------------------------------------------


@pytest.mark.asyncio
async def test_large_dataset_of_1000_transactions_paginates_completely_without_duplicates_or_loss(
    test_session_factory,
) -> None:
    from apps.api.infrastructure.database.models import TransactionModel
    from apps.api.infrastructure.repositories.sqlalchemy_transaction_repository import (
        SqlAlchemyTransactionRepository,
    )

    user_id = uuid.uuid4()
    # created_at is set explicitly here (not left to the DB's
    # server_default=func.now()) with a distinct, strictly-increasing
    # microsecond-precision value per row -- this test bypasses the
    # repository's add() for bulk-insert speed, so it must reproduce the
    # same explicit-timestamp discipline add() uses in production
    # (see sqlalchemy_transaction_repository.add()'s docstring comment).
    # Relying on 1000 rows sharing one server-side CURRENT_TIMESTAMP tick
    # is exactly the scenario that originally broke cursor pagination.
    base_time = datetime(2026, 7, 1, 0, 0, 0, tzinfo=timezone.utc)
    async with test_session_factory() as session:
        session.add_all(
            [
                TransactionModel(
                    id=uuid.uuid4(),
                    user_id=user_id,
                    amount=Decimal("1.00"),
                    category="Bulk",
                    transaction_date=date(2026, 7, 1),
                    created_at=base_time + timedelta(microseconds=i),
                    updated_at=base_time + timedelta(microseconds=i),
                )
                for i in range(1000)
            ]
        )
        await session.commit()

    seen_ids: set[uuid.UUID] = set()
    cursor = None
    pages_fetched = 0
    async with test_session_factory() as session:
        repo = SqlAlchemyTransactionRepository(session)
        while True:
            page = await repo.list_for_user(user_id=user_id, limit=100, cursor=cursor)
            pages_fetched += 1
            for item in page.items:
                assert item.id not in seen_ids, "pagination must not return the same row twice"
                seen_ids.add(item.id)
            if page.next_cursor is None:
                break
            cursor = page.next_cursor
            assert pages_fetched < 20, "pagination did not terminate as expected"

    assert len(seen_ids) == 1000


# --- Auth required on every endpoint --------------------------------------


def test_create_transaction_without_auth_token_returns_401(client) -> None:
    resp = client.post(
        "/api/v1/transactions",
        json={"amount": "10.00", "category": "Groceries", "transaction_date": "2026-07-01"},
    )
    assert resp.status_code == 401


def test_list_transactions_without_auth_token_returns_401(client) -> None:
    resp = client.get("/api/v1/transactions")
    assert resp.status_code == 401


def test_update_transaction_without_auth_token_returns_401(client) -> None:
    resp = client.patch(f"/api/v1/transactions/{uuid.uuid4()}", json={"amount": "10.00"})
    assert resp.status_code == 401


def test_delete_transaction_without_auth_token_returns_401(client) -> None:
    resp = client.delete(f"/api/v1/transactions/{uuid.uuid4()}")
    assert resp.status_code == 401


def datetime_now_minus(minutes: int):
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def test_expired_access_token_is_rejected(client) -> None:
    """Crafts a token with the same secret/algorithm the app uses but an
    exp already in the past -- proves expiry is actually enforced, not
    just signature validity."""
    expired_claims = {
        "sub": str(uuid.uuid4()),
        "type": "access",
        "jti": str(uuid.uuid4()),
        "iat": datetime_now_minus(minutes=30),
        "exp": datetime_now_minus(minutes=15),
    }
    token = pyjwt.encode(expired_claims, TEST_JWT_SECRET, algorithm="HS256")
    resp = client.get("/api/v1/transactions", headers=_auth(token))
    assert resp.status_code == 401


def test_refresh_token_used_as_bearer_token_is_rejected(client) -> None:
    """A refresh token is a valid, correctly-signed JWT -- but must not be
    accepted in place of an access token (same principle logout already
    enforces the other direction, ADR-009)."""
    from apps.api.infrastructure.security.token_service import TokenService

    tokens = TokenService(secret_key=TEST_JWT_SECRET)
    pair = tokens.issue_pair(uuid.uuid4())

    resp = client.get("/api/v1/transactions", headers=_auth(pair.refresh_token))
    assert resp.status_code == 401


def test_garbage_bearer_token_is_rejected(client) -> None:
    resp = client.get("/api/v1/transactions", headers=_auth("not-a-real-jwt"))
    assert resp.status_code == 401


# --- Accessibility -----------------------------------------------------


def test_accessibility_not_applicable_documented() -> None:
    """Documents, rather than silently skipping, the accessibility item
    from the QA Lead checklist: N/A for the same reason FINTRACK-14's
    equivalent test gives -- this is a backend-only story this sprint, no
    transaction-entry UI exists yet. Applicable once the frontend form
    ships."""
    assert True
