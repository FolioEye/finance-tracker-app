Feature: OAuth login via Google

  Scenario: New user completes Google OAuth and reaches the dashboard
    Given I am not registered with FinTrack
    When I click "Sign in with Google" and complete consent with a verified Google account
    Then a new FinTrack account is created linked to that Google identity
    And I am redirected to the dashboard with a valid session

  Scenario: Google denies or the user cancels consent
    Given I click "Sign in with Google"
    When I cancel or Google returns an error on the consent screen
    Then I am returned to the login page
    And I see a clear, non-technical error message
    And no partial account is created

  Scenario: Google email matches an existing password-registered account
    Given I already have a FinTrack account registered by password with email "user@example.com"
    When I sign in with Google using a Google account verified for "user@example.com"
    Then my existing account is linked to that Google identity
    And no duplicate account is created
    And I retain access to my existing data

  # Adapted from BA's original "forged callback state" wording: the
  # implemented architecture (ADR-016) uses client-side ID-token
  # verification (Google Identity Services), not a server-side
  # authorization-code redirect/callback with a CSRF state parameter --
  # so there is no "state" token in this flow to forge. The equivalent,
  # actually-testable security control is that a forged or tampered
  # Google ID token is rejected before any session is issued.
  Scenario: Forged or tampered Google ID token is rejected
    Given a sign-in attempt presents a Google ID token
    When that token's signature, issuer, or audience does not verify against Google's published keys
    Then the login is rejected
    And no session or JWT is issued
    And a security event should be logged
