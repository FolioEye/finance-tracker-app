# FINTRACK-22: Threshold-Based Alerts — 2pts (Jira key; drafted locally as FINTRACK-011)
# As a user, I want to be alerted when I'm close to or over a budget threshold, so that I can
# course-correct in real time instead of finding out at month-end.
# AC: fires at threshold crossing (e.g. 90% of budget) | fires on unusually large single transaction
#     | in-app only for this story | dismissing an alert doesn't disable future alerts | no spam --
#     max once per threshold crossing per period
# Out of scope: push notifications, email digests, custom user-defined thresholds (P1)

Feature: Threshold Alerts

  Scenario: Category spend crosses the 90% threshold
    Given my "Groceries" budget is "$400" and I have spent "$350"
    When a new transaction brings my spend to "$365"
    Then I should see an alert that I've crossed 90% of my "Groceries" budget

  Scenario: Spend stays well under threshold
    Given my "Groceries" budget is "$400" and I have spent "$100"
    When a new transaction brings my spend to "$120"
    Then no threshold alert should fire

  Scenario: Threshold is crossed multiple times via rapid transactions
    Given my spend is already just above the 90% threshold for "Groceries"
    When I add three more transactions in quick succession
    Then only one alert should fire for that threshold crossing, not one per transaction

  Scenario: Alert data is scoped to the authenticated user only
    Given I am authenticated as User A
    When I request my active alerts
    Then I should only see alerts generated from my own account's data
