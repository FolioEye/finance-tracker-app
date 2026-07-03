# FINTRACK-18: Subscription / Recurring-Charge Detection — 5pts (Jira key; drafted locally as FINTRACK-007)
# As a user, I want recurring charges detected automatically, so that I can see my subscriptions
# without manually identifying them.
# AC: pattern-match merchant+amount(tolerance)+interval across Transaction table | surfaced in a
#     dedicated Subscriptions view | user can confirm/dismiss/mark "not a subscription" | works on
#     manual+imported data only, no bank-sync | dismissed pattern not re-suggested | re-runs on new data
# Out of scope: cancellation automation, price-change alerts (P1 candidate)

Feature: Subscription Detection

  Scenario: Three monthly charges from the same merchant are flagged as a subscription
    Given I have three transactions from "NETFLIX.COM" of "$15.99" spaced roughly 30 days apart
    When subscription detection runs
    Then "NETFLIX.COM" should appear in my Subscriptions view

  Scenario: Irregular one-off charges from the same merchant are not flagged
    Given I have two unrelated one-time transactions from "AMAZON" with different amounts and no regular interval
    When subscription detection runs
    Then "AMAZON" should not appear in my Subscriptions view

  Scenario: Subscription amount varies slightly within tolerance
    Given I have three monthly transactions from "ELECTRIC CO" of "$84.50", "$91.20", "$88.00"
    When subscription detection runs
    Then "ELECTRIC CO" should still be flagged as a likely subscription within amount tolerance

  Scenario: Malicious merchant string from an imported transaction does not break detection
    Given an imported transaction has merchant field "<script>alert(1)</script>"
    When subscription detection runs and the merchant is displayed in the Subscriptions view
    Then the merchant name should be escaped/rendered as inert text
    And no script should execute
