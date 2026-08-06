Feature: OAuth login via Apple

  Scenario: New user completes Apple Sign-In and reaches the dashboard
    Given I am not registered with FinTrack
    When I complete "Sign in with Apple" successfully
    Then a new FinTrack account is created linked to my Apple identifier
    And I am redirected to the dashboard with a valid session

  Scenario: User cancels or Apple returns an error
    Given I start "Sign in with Apple"
    When I cancel or Apple returns an error during the flow
    Then I am returned to the login page
    And I see a clear, non-technical error message
    And no partial account is created

  Scenario: User signs in using Apple's private relay email
    Given I choose to hide my email during "Sign in with Apple"
    When I complete sign-in with Apple's generated private relay address
    Then my account is created and linked by my stable Apple user identifier, not the relay email alone
    And future sign-ins with the same Apple ID correctly match my existing account

  Scenario: Forged or unverifiable Apple identity token is rejected
    Given a sign-in attempt presents an Apple identity token
    When that token's signature does not verify against Apple's published public keys
    Then the login is rejected
    And no session or JWT is issued
    And a security event should be logged
