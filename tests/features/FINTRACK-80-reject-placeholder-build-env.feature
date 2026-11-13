# FINTRACK-80: Reject placeholder values in required production build config - 2pts (Mid-market tier)
# Parent epic: FINTRACK-12. Relates to: FINTRACK-47 (presence-only build guard, Done).
# As a release engineer, I want the production web build to fail when a required config value is an
# obvious placeholder, so that a "present but fake" value (e.g. https://placeholder.railway.app,
# live incident 2026-08-30) can never ship silently.
# AC: production build fails on placeholder-looking VITE_API_BASE_URL / VITE_GOOGLE_CLIENT_ID |
#     error names the variable and the reason, never echoes the value | a real value still builds |
#     dev server and vitest runs are not affected | change is build-time only (apps/web/vite.config.ts)
# Out of scope: post-build smoke test that calls the configured API URL, runtime validation,
#     Apple sign-in vars (optional by design), any secret rotation
# Assumptions: placeholder detection is a deny-list of obvious patterns (placeholder, example,
#     changeme, your-, todo, xxx, undefined, null, empty after trim), not a reachability check.
# Test data: all example values below are obviously fake; never use a real credential in a test.

Feature: Reject placeholder values in required production build config

  Scenario: Production build fails when the API base URL is a placeholder
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://placeholder.railway.app"
    And "VITE_GOOGLE_CLIENT_ID" is set to "1234567890-abcdefghijklmnop.apps.googleusercontent.com"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as having a placeholder value

  Scenario: Production build still succeeds with real config values
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://api.fintrack.example-corp.com"
    And "VITE_GOOGLE_CLIENT_ID" is set to "1234567890-abcdefghijklmnop.apps.googleusercontent.com"
    When the build configuration is loaded
    Then the build should proceed without error

  Scenario Outline: Obvious placeholder spellings are all rejected
    Given a production build is started
    And "VITE_GOOGLE_CLIENT_ID" is set to "<value>"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

    Examples:
      | value             |
      | your-client-id    |
      | CHANGEME          |
      | example-client-id |
      | undefined         |
      | null              |
      | TODO              |
      | xxx               |

  Scenario: A value consisting only of spaces is rejected as empty
    Given a production build is started
    And "VITE_GOOGLE_CLIENT_ID" is set to a value of only spaces
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

  Scenario: Placeholder check is case-insensitive and ignores surrounding whitespace
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "  HTTPS://PlaceHolder.Railway.app  "
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as having a placeholder value

  Scenario: Every offending variable is reported in one failure
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://placeholder.railway.app"
    And "VITE_GOOGLE_CLIENT_ID" is set to "your-client-id"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as having a placeholder value
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

  Scenario: An unset variable is still reported as missing, separately from a placeholder
    Given a production build is started
    And "VITE_API_BASE_URL" is not set
    And "VITE_GOOGLE_CLIENT_ID" is set to "your-client-id"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as missing
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

  Scenario: Build error never leaks the configured value
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://placeholder.railway.app/?key=FAKE-TOKEN-0000-NOT-A-REAL-SECRET"
    When the build configuration is loaded
    Then the build should fail
    And the error message should not contain "https://placeholder.railway.app/?key=FAKE-TOKEN-0000-NOT-A-REAL-SECRET"
    And the error message should not contain "FAKE-TOKEN-0000-NOT-A-REAL-SECRET"

  Scenario: Dev server and test runs are not subject to the placeholder check
    Given "VITE_API_BASE_URL" is set to "https://placeholder.railway.app"
    When the dev server or vitest starts
    Then no placeholder error should be raised
