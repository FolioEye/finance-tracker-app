# FINTRACK-15: Add Manual Transaction — 3pts (Jira key; drafted locally as FINTRACK-004)
# As a privacy-first user, I want to manually add a transaction with amount, category, and date,
# so that I can track spending without connecting a bank account.
# AC: positive decimal amount (2dp max) | required category, custom allowed | optional note/merchant
#     | appears immediately in list + affects budget total | editable/deletable | sanitised on input
# Out of scope: recurring transactions (FINTRACK-18), multi-currency, receipt attachments (P1 OCR)

Feature: Add Manual Transaction

  Scenario: Successfully add an expense transaction
    Given I am authenticated as a registered user
    When I enter amount "42.50", category "Groceries", date "2026-07-02"
    And I click "Save Transaction"
    Then the transaction appears in my transaction list
    And my budget total for "Groceries" decreases by "42.50"

  Scenario: Attempt to add transaction with negative amount
    Given I am authenticated as a registered user
    When I enter amount "-15.00" in the transaction form
    And I click "Save Transaction"
    Then I should see validation error "Amount must be a positive number"
    And no transaction should be created

  Scenario: Add transaction at maximum amount boundary
    Given I am authenticated as a registered user
    When I enter amount "999999999.99" in the transaction form
    Then I should see validation error "Amount exceeds maximum allowed limit"

  Scenario: Attempt SQL injection in transaction description
    Given I am authenticated as a registered user
    When I enter description "'; DROP TABLE transactions; --"
    And I click "Save Transaction"
    Then the input should be sanitised
    And I should see validation error "Invalid characters detected"
    And the database should remain intact
    And a security event should be logged
