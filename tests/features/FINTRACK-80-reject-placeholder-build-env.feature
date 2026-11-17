# FINTRACK-80: Reject placeholder values in required production build config - 2pts (Mid-market tier)
# Parent epic: FINTRACK-12. Relates to: FINTRACK-47 (presence-only build guard, Done).
# As a release engineer, I want the production web build to fail when a required config value is an
# obvious placeholder, so that a "present but fake" value (e.g. https://placeholder.railway.app,
# live incident 2026-08-30) can never ship silently.
#
# Acceptance criteria (ids are permanent; never renumber or reuse):
#   FINTRACK-80-AC1: the production build fails when VITE_API_BASE_URL or VITE_GOOGLE_CLIENT_ID
#                    matches the deny-list defined in AC5.
#   FINTRACK-80-AC2: the error names each offending variable and the reason ("placeholder" or
#                    "missing"), reports every offender in one failure, and never echoes the value.
#   FINTRACK-80-AC3: a real value that matches no deny-list rule still builds.
#   FINTRACK-80-AC4: dev server and vitest runs are not subject to the check (build-time only,
#                    apps/web/vite.config.ts).
#   FINTRACK-80-AC5: matching rule (applied to the value after trimming surrounding whitespace and
#                    lower-casing; the rule is fixed per pattern, there is no other matching mode):
#                      PART-OF-VALUE (substring) patterns - rejected if the pattern appears anywhere:
#                        placeholder | changeme | your- | example
#                      WHOLE-VALUE (exact) patterns - rejected only if the entire value equals it:
#                        undefined | null | todo | xxx | (empty string after trim)
#                    A whole-value pattern appearing inside a longer value is NOT a match.
#
# Out of scope: post-build smoke test that calls the configured API URL, runtime validation,
#     Apple sign-in vars (optional by design), any secret rotation, reachability checks.
# Assumptions: detection is the deny-list above, not a reachability check. "example" is a substring
#     pattern, so reserved example domains (e.g. example.com) are rejected by design.
# Test data: all example values are obviously fake; never use a real credential in a test.
# Allowed (happy-path) values must contain none of the deny-list patterns.

Feature: Reject placeholder values in required production build config

  # FINTRACK-80-AC1
  Scenario: Production build fails when the API base URL is a placeholder
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://placeholder.railway.app"
    And "VITE_GOOGLE_CLIENT_ID" is set to "1234567890-abcdefghijklmnop.apps.googleusercontent.com"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as having a placeholder value

  # FINTRACK-80-AC3
  Scenario: Production build still succeeds with real config values
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://api.fintrack.app"
    And "VITE_GOOGLE_CLIENT_ID" is set to "1234567890-abcdefghijklmnop.apps.googleusercontent.com"
    When the build configuration is loaded
    Then the build should proceed without error

  # FINTRACK-80-AC1, FINTRACK-80-AC5 (part-of-value patterns: placeholder, changeme, your-, example)
  Scenario Outline: A value containing a part-of-value pattern anywhere is rejected
    Given a production build is started
    And "VITE_GOOGLE_CLIENT_ID" is set to "<value>"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

    Examples:
      | value                                           |
      | your-client-id                                  |
      | CHANGEME                                        |
      | example-client-id                               |
      | 1234567890-placeholder.apps.googleusercontent.com |
      | 1234567890-changeme-abc.apps.googleusercontent.com |

  # FINTRACK-80-AC1, FINTRACK-80-AC5 (whole-value patterns: undefined, null, todo, xxx)
  Scenario Outline: A value that is entirely a whole-value pattern is rejected
    Given a production build is started
    And "VITE_GOOGLE_CLIENT_ID" is set to "<value>"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

    Examples:
      | value     |
      | undefined |
      | null      |
      | TODO      |
      | xxx       |

  # FINTRACK-80-AC3, FINTRACK-80-AC5 (whole-value patterns do not match inside a longer value)
  Scenario Outline: A whole-value pattern appearing inside a longer real value is not rejected
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://api.fintrack.app"
    And "VITE_GOOGLE_CLIENT_ID" is set to "<value>"
    When the build configuration is loaded
    Then the build should proceed without error

    Examples:
      | value                                            |
      | 1234567890-nullabcdefgh.apps.googleusercontent.com |
      | 1234567890-todolist.apps.googleusercontent.com     |
      | 1234567890-xxxabcdef.apps.googleusercontent.com    |
      | 1234567890-undefinedabc.apps.googleusercontent.com |

  # FINTRACK-80-AC1, FINTRACK-80-AC5 (empty after trim is a whole-value pattern)
  Scenario: A value consisting only of spaces is rejected as empty
    Given a production build is started
    And "VITE_GOOGLE_CLIENT_ID" is set to a value of only spaces
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

  # FINTRACK-80-AC5 (normalisation: trim + lower-case before matching)
  Scenario: Placeholder check is case-insensitive and ignores surrounding whitespace
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "  HTTPS://PlaceHolder.Railway.app  "
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as having a placeholder value

  # FINTRACK-80-AC2
  Scenario: Every offending variable is reported in one failure
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://placeholder.railway.app"
    And "VITE_GOOGLE_CLIENT_ID" is set to "your-client-id"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as having a placeholder value
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

  # FINTRACK-80-AC2
  Scenario: An unset variable is still reported as missing, separately from a placeholder
    Given a production build is started
    And "VITE_API_BASE_URL" is not set
    And "VITE_GOOGLE_CLIENT_ID" is set to "your-client-id"
    When the build configuration is loaded
    Then the build should fail
    And the error should name "VITE_API_BASE_URL" as missing
    And the error should name "VITE_GOOGLE_CLIENT_ID" as having a placeholder value

  # FINTRACK-80-AC2 (security: a rejected value may carry a secret and must never be echoed)
  Scenario: Build error never leaks the configured value
    Given a production build is started
    And "VITE_API_BASE_URL" is set to "https://placeholder.railway.app/?key=FAKE-TOKEN-0000-NOT-A-REAL-SECRET"
    When the build configuration is loaded
    Then the build should fail
    And the error message should not contain "https://placeholder.railway.app/?key=FAKE-TOKEN-0000-NOT-A-REAL-SECRET"
    And the error message should not contain "FAKE-TOKEN-0000-NOT-A-REAL-SECRET"

  # FINTRACK-80-AC4
  Scenario: The dev server is not subject to the placeholder check
    Given "VITE_API_BASE_URL" is set to "https://placeholder.railway.app"
    When the dev server starts
    Then no placeholder error should be raised

  # FINTRACK-80-AC4
  Scenario: A vitest run is not subject to the placeholder check
    Given "VITE_API_BASE_URL" is set to "https://placeholder.railway.app"
    When vitest starts
    Then no placeholder error should be raised
