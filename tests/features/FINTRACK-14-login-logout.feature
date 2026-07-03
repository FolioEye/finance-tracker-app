# FINTRACK-14: Login / Logout — 2pts (Jira key; drafted locally as FINTRACK-003)
# As a registered user, I want to log in and log out securely, so that only I can access my data.
# AC: email+password login | generic error on failure (no user enumeration) | access token
#     15min + httpOnly refresh token 7d on success | rate-limited 5 attempts/15min | logout
#     invalidates session | session persists until expiry or explicit logout
# Out of scope: multi-device session list / "log out everywhere" (P2), passwordless (P1)

Feature: Login and Logout

  Scenario: Successfully log in with correct credentials
    Given I have a registered account
    When I enter my correct email and password
    And I click "Log In"
    Then I should be redirected to my dashboard
    And a short-lived access token and httpOnly refresh token should be issued

  Scenario: Attempt to log in with an incorrect password
    Given I have a registered account
    When I enter my email and an incorrect password
    Then I should see a generic error "Invalid email or password"
    And the error should not reveal whether the email exists

  Scenario: Sixth login attempt within 15 minutes is rate-limited
    Given I have made 5 failed login attempts for the same account within 15 minutes
    When I attempt to log in a 6th time
    Then I should see error "Too many attempts, try again later"
    And the attempt should not be processed against the database

  Scenario: Attempt SQL injection in the email field during login
    Given I am on the login page
    When I enter email "'; DROP TABLE users; --" and any password
    And I click "Log In"
    Then the input should be sanitised
    And I should see the generic invalid-credentials error
    And the database should remain intact
    And a security event should be logged
