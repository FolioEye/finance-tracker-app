Feature: Frontend application scaffold

  Scenario: Production build succeeds and serves a working root page
    Given the apps/web source tree is checked out
    When I run "npm run build"
    Then the build completes with exit code 0
    And a static bundle is produced in the configured output directory
    And serving that bundle locally returns a 200 response with visible content on "/"

  Scenario: A TypeScript type error fails the build
    Given a source file contains a deliberate type error
    When I run "npm run build"
    Then the build fails with a non-zero exit code
    And the reported error names the exact file and line
    And no build artifact is produced

  # Adapted from BA's original branching wording ("fails OR succeeds with
  # safe defaults") which isn't valid single-outcome Gherkin. Asserting
  # the fail-loudly branch as the required behaviour, since silently
  # baking an undefined API base URL into a production bundle is a
  # zero-trust violation, not an acceptable fallback -- this is currently
  # NOT what the code does (see FINTRACK-47, raised this pass).
  Scenario: Build fails loudly when required environment variables are missing
    Given VITE_API_BASE_URL is not set for the build
    When I run "npm run build"
    Then the build fails with a clear, named "missing required config" error
    And no build artifact is produced

  Scenario: Attempt to smuggle a secret into the client bundle
    Given a developer accidentally references "process.env.SOME_SERVER_SECRET" in client-side code
    When I run "npm run build"
    Then the build should fail or warn loudly that a server-only variable was referenced client-side
    And the resulting bundle must not contain the secret's value
    And a security event should be logged if the build tooling supports it
