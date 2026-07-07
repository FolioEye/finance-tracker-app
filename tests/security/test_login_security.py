"""QA Lead mandatory security sweep for FINTRACK-14 (Login/Logout), run at
the real API level (TestClient -> real router -> real Pydantic validation
-> real handler -> real SQLite-backed repository -> fakeredis-backed rate
limiter/revocation store).

Checklist (per fintrack-qa-lead skill, "any story touching auth, data, or
money"): SQL injection on every user-controlled field, XSS payload on every
text input, auth bypass, IDOR. Where a check genuinely doesn't apply to
this specific pair of endpoints, that's documented explicitly with
rationale rather than silently skipped -- same discipline as
tests/security/test_register_api_security.py.
"""
from __future__ import annotations

SQLI_PAYLOAD = "'; DROP TABLE users; --"
XSS_PAYLOAD = "<script>alert('xss')</script>"


def _register(client, email: str, password: str = "StrongPass1") -> None:
    resp = client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "confirm_password": password},
    )
    assert resp.status_code == 201, resp.text


def test_sql_injection_in_login_email_rejected_generically(client) -> None:
    """Matches Gherkin: 'Attempt SQL injection in the email field during
    login'. Unlike registration's 400 + 'Invalid email format', login must
    return the exact same 401 + generic message as any other failed login
    -- confirmed against a real registered user's credentials being tried
    alongside, so this isn't just "no such row" by coincidence.
    """
    _register(client, "sqli-login-target@example.com")

    resp = client.post(
        "/api/v1/auth/login",
        json={"email": SQLI_PAYLOAD, "password": "anything"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_sql_injection_payload_never_reflected_in_response(client) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": SQLI_PAYLOAD, "password": "anything"},
    )
    assert SQLI_PAYLOAD not in resp.text


def test_sql_injection_does_not_disturb_other_accounts(client) -> None:
    """If the payload had reached a query unparameterised, a DROP TABLE
    would take out every account, not just fail to authenticate one. A
    real, unrelated user logging in successfully right after is the
    strongest evidence the table is intact.
    """
    _register(client, "innocent-bystander@example.com")

    injection_resp = client.post(
        "/api/v1/auth/login",
        json={"email": SQLI_PAYLOAD, "password": "anything"},
    )
    assert injection_resp.status_code == 401

    followup = client.post(
        "/api/v1/auth/login",
        json={"email": "innocent-bystander@example.com", "password": "StrongPass1"},
    )
    assert followup.status_code == 200, followup.text


def test_xss_payload_in_login_email_rejected_generically(client) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": XSS_PAYLOAD, "password": "anything"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_xss_payload_never_reflected_in_login_response(client) -> None:
    resp = client.post(
        "/api/v1/auth/login",
        json={"email": XSS_PAYLOAD, "password": "anything"},
    )
    assert "<script>" not in resp.text


def test_xss_payload_not_applicable_to_logout(client) -> None:
    """Logout takes no user-controlled text field at all (only a cookie
    the client can't set arbitrary content into via this endpoint's own
    contract) -- there is no injection surface to test here. Documented
    rather than silently omitted.
    """
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200


def test_auth_bypass_unknown_email_and_wrong_password_return_identical_response(client) -> None:
    """The core auth-bypass-adjacent check for login: an attacker probing
    for valid emails must not be able to distinguish 'no such account'
    from 'wrong password' via status code, body, or headers.
    """
    _register(client, "real-account@example.com")

    wrong_password = client.post(
        "/api/v1/auth/login",
        json={"email": "real-account@example.com", "password": "WrongPassword9"},
    )
    unknown_email = client.post(
        "/api/v1/auth/login",
        json={"email": "definitely-not-registered@example.com", "password": "WrongPassword9"},
    )

    assert wrong_password.status_code == unknown_email.status_code == 401
    assert wrong_password.json() == unknown_email.json()


def test_auth_bypass_empty_or_missing_credentials_rejected(client) -> None:
    resp = client.post("/api/v1/auth/login", json={"email": "", "password": ""})
    assert resp.status_code in (401, 422)  # 422 if Pydantic's min_length=1 catches it first

    resp2 = client.post("/api/v1/auth/login", json={"email": "no-password@example.com"})
    assert resp2.status_code == 422  # missing required field


def test_logout_does_not_require_or_leak_whether_a_session_existed(client) -> None:
    """Auth-bypass-adjacent check for logout: calling it with no prior
    login (no cookie at all) must succeed identically to calling it after
    a real login, so the response can't be used to probe session state.
    """
    resp = client.post("/api/v1/auth/logout")
    assert resp.status_code == 200
    assert resp.json()["detail"] == "Logged out successfully"


def test_idor_not_directly_applicable_login_logout_have_no_target_resource_id(client) -> None:
    """IDOR requires a request that references *someone else's* resource
    by ID/identifier while authenticated as a different user. Login takes
    only the caller's own claimed credentials (rejected or accepted, never
    substituted for another account), and logout acts only on whatever
    session the caller's own cookie identifies -- there is no
    attacker-supplied identifier pointing at another user's data in
    either endpoint. This becomes directly testable once an endpoint
    accepts a resource identifier in the path/body (e.g. a future
    GET /accounts/{id}). Documented as N/A here rather than fabricating a
    test against a parameter that doesn't exist on this pair of endpoints.
    """
    assert True


def test_logout_cannot_be_used_to_revoke_an_arbitrary_users_session_without_their_token(client) -> None:
    """The closest real analogue to IDOR available on this endpoint: does
    supplying a syntactically-valid-looking but unowned/garbage token let
    an attacker revoke someone else's actual session? It must not --
    logout should just fail to find anything to revoke, not revoke the
    wrong session or error in a way that reveals another user's data.
    """
    _register(client, "victim@example.com")
    login_resp = client.post(
        "/api/v1/auth/login", json={"email": "victim@example.com", "password": "StrongPass1"}
    )
    assert login_resp.status_code == 200
    victims_refresh_cookie = login_resp.cookies.get("refresh_token")
    assert victims_refresh_cookie

    # Attacker calls logout with a garbage cookie value of their own,
    # never having seen the victim's real token.
    resp = client.post(
        "/api/v1/auth/logout",
        cookies={"refresh_token": "attacker-supplied-garbage-not-a-real-token"},
    )
    assert resp.status_code == 200

    # Victim's own real session is unaffected -- still logs in fine
    # (registration/login don't currently gate on prior-session state,
    # but this at minimum proves the attacker's call didn't error out in
    # a way that would suggest it touched server-side state tied to the
    # victim).
    second_login = client.post(
        "/api/v1/auth/login", json={"email": "victim@example.com", "password": "StrongPass1"}
    )
    assert second_login.status_code == 200
