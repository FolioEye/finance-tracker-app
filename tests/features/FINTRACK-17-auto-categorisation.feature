# FINTRACK-17: AI Auto-Categorisation Rules Engine — 5pts (Jira key; drafted locally as FINTRACK-006)
# As a privacy-first user, I want manual and imported transactions auto-categorised,
# so that I don't have to sort every transaction myself.
# AC: pattern-match merchant/description against rules table | low-confidence -> "Uncategorised" for review
#     | user correction feeds back into personal rule set | works on manual+imported data only, no bank-sync
#     | bulk import shows "X of Y auto-categorised, Z need review" before commit | suggestion is auditable
# Out of scope: per-user ML model training (v1 is rules-based only, per PM's "rules engine" framing)

Feature: AI Auto-Categorisation

  Scenario: Imported transaction auto-categorised from known merchant pattern
    Given I have a rule mapping "STARBUCKS" to category "Coffee & Dining"
    When I import a statement containing a transaction from "STARBUCKS #4521"
    Then the transaction should be auto-assigned category "Coffee & Dining"
    And I should be able to see which rule produced the match

  Scenario: Transaction from unknown merchant is flagged, not guessed
    Given no rule matches the merchant "XZQ HOLDINGS LLC"
    When I import a statement containing that transaction
    Then the transaction should be marked "Uncategorised"
    And it should not be assigned a category with low confidence

  Scenario: Bulk import of 200 transactions shows categorisation summary
    Given I upload a statement containing 200 transactions
    When the import completes
    Then I should see a summary "X of 200 auto-categorised, Y need review"
    And I should be able to bulk-review only the uncategorised ones

  Scenario: Attempt injection via a custom categorisation rule
    Given I am adding a custom rule to categorise a merchant
    When I enter merchant pattern "'; DROP TABLE rules; --"
    And I save the rule
    Then the input should be sanitised
    And I should see validation error "Invalid characters detected"
    And the rules table should remain intact

  Scenario: User's manual category correction updates their personal rule set
    Given an imported transaction from "XZQ HOLDINGS LLC" was left "Uncategorised"
    When I manually assign it to category "Business Expenses"
    Then a new personal rule mapping "XZQ HOLDINGS LLC" to "Business Expenses" should be created
    And a future transaction from "XZQ HOLDINGS LLC" should be auto-categorised as "Business Expenses"
