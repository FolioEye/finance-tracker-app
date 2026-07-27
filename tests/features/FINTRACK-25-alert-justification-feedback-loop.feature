Feature: Alert Justification Feedback Loop

  Scenario: User justifies a large-transaction alert and a similar future transaction does not re-alert
    Given I have a "LARGE_TRANSACTION" alert for "Travel" from a transaction of "$900"
    When I justify that alert as "expected"
    And a new transaction of "$850" is added in the "Travel" category
    Then no new "LARGE_TRANSACTION" alert should fire for that transaction

  Scenario: A transaction that exceeds every previously justified amount for a category still alerts
    Given I have justified a "LARGE_TRANSACTION" alert for "Travel" up to "$900"
    When a new transaction of "$1500" is added in the "Travel" category
    Then a new "LARGE_TRANSACTION" alert should fire for that transaction

  Scenario: A plain dismiss does not suppress future similar alerts
    Given I have a "LARGE_TRANSACTION" alert for "Electronics" from a transaction of "$700"
    When I dismiss that alert without justifying it
    And a new transaction of "$650" is added in the "Electronics" category
    Then a new "LARGE_TRANSACTION" alert should fire for that transaction

  Scenario: Attempt to justify a threshold-crossing alert
    Given I have a "THRESHOLD_CROSSING" alert for "Groceries"
    When I attempt to justify that alert as "expected"
    Then I should see validation error "Justification only applies to large-transaction alerts"
    And no justification should be recorded

  Scenario: Attempt to justify another user's alert
    Given I am authenticated as User A
    And User B has a "LARGE_TRANSACTION" alert with a known alert id
    When I attempt to justify User B's alert using its alert id
    Then the request should be rejected
    And User B's alert should remain unjustified

  Scenario: Attempt SQL injection in the alert id path parameter
    Given I am authenticated as a registered user
    When I submit "'; DROP TABLE alerts; --" as the alert id to justify
    Then the input should be rejected as a malformed identifier
    And the database should remain intact
    And a security event should be logged
