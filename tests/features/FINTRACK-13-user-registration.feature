# FINTRACK-13: User Registration — 3pts (Jira key; drafted locally as FINTRACK-002)
# As a new user, I want to register with email and password, so that I can create a private
# account to track my finances.
# AC: email + password + confirm | password meets minimum strength | email must be unique
#     | auto-login + redirect to onboarding on success | password hashed (bcrypt), never
#     logged/stored plaintext | soft email verification (account usable immediately, nudge shown)
# Out of scope: OAuth (P1), MFA enrollment (P1)

Feature: User Registration

  Scenario: Successfully register a new account
    Given I am on the registration page
    When I enter email "newuser@example.com" and a password meeting strength requirements
    And I click "Create Account"
    Then my account should be created
    And I should be logged in and redirected to onboarding

  Scenario: Attempt to register with an already-registered email
    Given an account already exists for "existing@example.com"
    When I attempt to register with email "existing@example.com"
    Then I should see error "An account with this email already exists"
    And no duplicate account should be created

  Scenario: Attempt to register with a weak password
    Given I am on the registration page
    When I enter password "12345"
    Then I should see validation error "Password does not meet minimum strength requirements"
    And no account should be created

  Scenario: Attempt SQL injection in email field during registration
    Given I am on the registration page
    When I enter email "'; DROP TABLE users; --"
    And I click "Create Account"
    Then the input should be sanitised
    And I should see validation error "Invalid email format"
    And the database should remain intact
    And a security event should be logged
