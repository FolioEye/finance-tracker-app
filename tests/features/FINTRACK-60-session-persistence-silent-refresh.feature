# FINTRACK-60 — Session persistence via silent token refresh
# Epic: EP-01 Authentication | Story points: 5 | Parent business case: FINTRACK-51 / FINTRACK-38
# Acceptance criteria: FINTRACK-60-AC1 .. FINTRACK-60-AC6
# Scenario mix: 1 happy, 1 negative, 2 edge, 2 security (6 total)

Feature: Session persistence via silent token refresh
  As a returning FinTrack user
  I want my session to survive a page refresh, a reopened tab, or a closed browser
  So that I am not sent back to the Google sign-in screen while a valid 7-day refresh cookie already exists

  Background:
    Given the API exposes POST /api/v1/auth/refresh
    And the access token is held in memory only with a 15 minute lifetime
    And a successful login sets a 7-day httpOnly refresh_token cookie

  # --- HAPPY PATH (AC1, AC2, AC3) ---
  @AC1 @AC2 @AC3 @happy
  Scenario: Returning user with a valid refresh cookie stays signed in after a page refresh
    Given I signed in successfully and hold a valid refresh_token cookie
    And my in-memory access token has been discarded by the page reload
    When I refresh the browser on /dashboard
    Then the web app should call POST /api/v1/auth/refresh before ProtectedRoute evaluates my session
    And the response should return a new 15 minute access token
    And the refresh_token cookie should be rotated to a new value
    And I should land on /dashboard still authenticated
    And I should never see the /login screen, not even momentarily

  # --- NEGATIVE (AC4) ---
  @AC4 @negative
  Scenario: Expired refresh cookie sends the user to login exactly once
    Given my refresh_token cookie has passed its 7-day expiry
    When I open the application at /dashboard
    Then POST /api/v1/auth/refresh should respond 401 Unauthorized
    And no new access token should be issued
    And no new refresh_token cookie should be set
    And I should be redirected to /login exactly once with no redirect loop

  # --- EDGE CASE 1 (AC2, AC4) ---
  @AC2 @AC4 @edge
  Scenario: First-time visitor with no refresh cookie at all is not blocked by the refresh attempt
    Given I have never signed in and hold no refresh_token cookie
    When I open the application at /dashboard
    Then the silent refresh attempt should fail fast without throwing an unhandled error
    And I should be redirected to /login
    And the login screen should render normally rather than an error boundary

  # --- EDGE CASE 2 (AC3) ---
  @AC3 @edge
  Scenario: Deep link is preserved across a silent refresh
    Given I signed in successfully and hold a valid refresh_token cookie
    And my in-memory access token has been discarded by the page reload
    When I navigate directly to /transactions?month=2026-09
    Then the silent refresh should complete before any redirect decision is made
    And I should land on /transactions?month=2026-09 with the month filter intact
    And I should not be bounced to /dashboard or /login

  # --- SECURITY 1 (AC5) ---
  @AC5 @security
  Scenario: A rotated refresh token cannot be replayed
    Given I hold a valid refresh_token cookie with value "OLD_REFRESH_TOKEN"
    When POST /api/v1/auth/refresh succeeds and rotates the cookie
    And a request is replayed to POST /api/v1/auth/refresh presenting "OLD_REFRESH_TOKEN"
    Then the replayed request should be rejected with 401 Unauthorized
    And no access token should be issued for the replayed request
    And a security event should be logged recording the reuse attempt

  # --- SECURITY 2 (AC6) ---
  @AC6 @security
  Scenario: Tokens are never exposed to client-side script or persistent storage
    Given I have completed a successful silent refresh
    When I inspect the browser storage and the refresh response body
    Then the access token should not be present in localStorage or sessionStorage
    And the refresh_token cookie should not be readable via document.cookie
    And the refresh_token cookie should carry the HttpOnly, Secure and SameSite attributes
    And the refresh token value should not appear anywhere in the response body
