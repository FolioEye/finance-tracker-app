# FINTRACK-19: Spending Insights Dashboard — 3pts (Jira key; drafted locally as FINTRACK-008)
# As a user, I want a dashboard summarizing spending by category and over time, so that I can
# understand my financial picture at a glance.
# AC: current-month total by category | trend view (3-6 months) | updates immediately on new
#     transaction | empty state has a clear CTA, not a blank/broken screen | loads acceptably at 1000+ txns
# Out of scope: net worth (P1), forecasting (P1), custom date-range filtering

Feature: Spending Insights Dashboard

  Scenario: Dashboard correctly totals and categorises current-month spending
    Given I have transactions this month totalling "$450" across 3 categories
    When I open my dashboard
    Then I should see "$450" as my total spend
    And I should see a per-category breakdown that sums to "$450"

  Scenario: New user with zero transactions sees an empty state
    Given I have no transactions yet
    When I open my dashboard
    Then I should see an empty state with a call-to-action to add my first transaction
    And I should not see an error or broken chart

  Scenario: Dashboard loads acceptably with a large transaction history
    Given I have 1000+ transactions
    When I open my dashboard
    Then the dashboard should load within an acceptable time bound
    And totals should still be accurate

  Scenario: Attempt to access another user's dashboard data
    Given I am authenticated as User A
    When I attempt to request dashboard data scoped to User B's account ID
    Then the request should be rejected
    And no data belonging to User B should be returned
