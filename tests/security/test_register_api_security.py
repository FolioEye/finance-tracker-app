"""QA Lead mandatory security sweep for FINTRACK-13, run at the real API
level (through TestClient -> real router -> real Pydantic validation ->
real handler -> real SQLite-backed repository), complementing Tech Lead's
existing handler-level test in tests/security/test_register_security.py.

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on
every text input, auth bypass, IDOR. The last two are addressed with an
explicit N/A + rationale rather than a fabricated test, since this
specific endpoint has no authentication or per-user resource to attack.
"""
from __future__ import annotations

SQLI_PAYLOAD = "'; DROP TABLE users; --"
XSS_PAYLOAD = "<script>alert('xss')</script>"


def test_sql_injection_in_email_field_rejected(client) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": SQLI_PAYLOAD, "password": "StrongPass1", "confirm_password": "StrongPass1"},
    )
    assert resp.status_code == 400


def test_sql_injection_shaped_password_is_hashed_not_executed(client) -> None:
    """The password field is never used to build a query -- it only ever
    reaches bcrypt.hashpw() as opaque bytes -- so a SQLi-shaped password
    should register successfully like any other string, not error out.
    A 500 or a DB-shape error here would indicate the string leaked into
    a query path somewhere; a clean 201 confirms it didn't.
    """
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "sqli-in-password-field@example.com",
            "password": "Str0ng'; DROP TABLE users; --",
            "confirm_password": "Str0ng'; DROP TABLE users; --",
        },
    )
    assert resp.status_code == 201, resp.text


def test_sql_injection_shaped_confirm_password_mismatch_rejected_safely(client) -> None:
    """confirm_password only ever reaches a string equality check
    (RegisterUserHandler.handle) -- a SQLi-shaped mismatch must fail as a
    plain validation error, not as a DB or server error.
    """
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "sqli-in-confirm-field@example.com",
            "password": "StrongPass1",
            "confirm_password": "'; DROP TABLE users; --",
        },
    )
    assert resp.status_code == 400
    assert resp.json()["detail"] == "Passwords do not match"


def test_xss_payload_in_email_rejected_by_format_validation(client) -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": XSS_PAYLOAD, "password": "StrongPass1", "confirm_password": "StrongPass1"},
    )
    assert resp.status_code == 400


def test_xss_payload_in_email_never_reflected_in_response_body(client) -> None:
    """Even though the request is rejected, confirm the raw payload isn't
    echoed back unescaped anywhere in the error response (defence in
    depth -- relevant if this error message is ever rendered as HTML).
    """
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": XSS_PAYLOAD, "password": "StrongPass1", "confirm_password": "StrongPass1"},
    )
    assert "<script>" not in resp.text


def test_xss_payload_as_local_part_of_otherwise_valid_email_rejected(client) -> None:
    """A more targeted XSS attempt shaped to look closer to a real email
    local-part, to check the format regex isn't only catching the
    obvious `<script>` case.
    """
    resp = client.post(
        "/api/v1/auth/register",
        json={
            "email": "<img src=x onerror=alert(1)>@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert resp.status_code == 400


def test_auth_bypass_not_applicable(client) -> None:
    """Registration is intentionally an unauthenticated endpoint -- there
    is no auth check to bypass. Documented explicitly (with a passing
    assertion that it works with zero Authorization header, by design)
    rather than silently omitted from the checklist.
    """
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": "no-auth-required@example.com", "password": "StrongPass1", "confirm_password": "StrongPass1"},
    )
    assert resp.status_code == 201


def test_idor_not_applicable() -> None:
    """Registration creates a brand-new resource scoped to the caller --
    there is no existing per-user resource for another party to access
    out of scope. IDOR becomes directly testable starting with
    FINTRACK-14 (Login) and any endpoint that reads/writes a specific
    user's data. Documented as N/A here rather than fabricating a test
    against an endpoint that has nothing to be an IDOR victim of.
    """
    assert True


def test_registration_rate_limited_after_threshold(client) -> None:
    """PM AC + constraint matrix: registration endpoint is rate-limited.
    Test config (apps/api/config.py defaults, unless overridden) allows
    5 attempts / 15 minutes. The 6th attempt in the same window from the
    same client must be rejected with 429.
    """
    for i in range(5):
        resp = client.post(
            "/api/v1/auth/register",
            json={
                "email": f"rate-limit-probe-{i}@example.com",
                "password": "StrongPass1",
                "confirm_password": "StrongPass1",
            },
        )
        assert resp.status_code == 201, f"attempt {i} unexpectedly failed: {resp.text}"

    sixth = client.post(
        "/api/v1/auth/register",
        json={
            "email": "rate-limit-probe-6@example.com",
            "password": "StrongPass1",
            "confirm_password": "StrongPass1",
        },
    )
    assert sixth.status_code == 429
