# FINTRACK-20: Simple Budget Tracking — 3pts (Jira key; drafted locally as FINTRACK-009)
# As a user, I want to set a monthly spending limit per category, so that I can track whether
# I'm staying within budget.
# AC: set monthly budget per category | progress shown as actual vs. limit | resets each calendar
#     month | editable/removable anytime | categories with no budget just show spend, no false "over" state
# Out of scope: rollover budgets, multi-month planning

Feature: Simple Budget Tracking

  Scenario: Track spend against a category budget
    Given I set a "$500" monthly budget for "Groceries"
    When I spend "$300" in "Groceries" this month
    Then I should see my "Groceries" budget at "60% used"

  Scenario: Attempt to set an invalid budget limit
    Given I am setting a budget for "Dining"
    When I enter a budget amount of "$0" or a negative number
    Then I should see validation error "Budget must be a positive amount"
    And no budget should be saved

  Scenario: Spending exceeds the category budget
    Given I have a "$200" monthly budget for "Entertainment"
    When my spend in "Entertainment" reaches "$250"
    Then I should see a clear "over budget" indicator
    And the overage should be visible, not silently capped at 100%

  Scenario: Attempt to access another user's budget data
    Given I am authenticated as User A
    When I attempt to request budget data scoped to User B's account ID
    Then the request should be rejected

  Scenario: Budget progress resets at the start of a new calendar month
    Given I spent "$450" against my "$500" "Groceries" budget last month
    When the calendar month rolls over
    Then my "Groceries" budget progress for the new month should show "$0" spent
    And last month's spend should not carry into the new month's total

  Scenario: User edits an existing budget limit
    Given I have a "$500" monthly budget for "Groceries"
    When I change the limit to "$600"
    Then my "Groceries" budget should reflect the new "$600" limit
    And my progress percentage should be recalculated against the new limit

  Scenario: User removes an existing budget
    Given I have a "$500" monthly budget for "Groceries"
    When I remove the "Groceries" budget
    Then "Groceries" should no longer show a budget limit or progress indicator
    And my past spend in "Groceries" should remain visible in transaction history

  Scenario: Category with no budget set shows spend without a false "over" state
    Given I have no budget set for "Entertainment"
    And I have spent "$120" in "Entertainment" this month
    Then I should see "$120" spent for "Entertainment"
    And I should not see any "over budget" or percentage-used indicator for it
