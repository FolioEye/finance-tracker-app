# FINTRACK-21: Weekly "What Should I Do Next" Recommendation — 5pts (Jira key; drafted locally as FINTRACK-010)
# As a user, I want a weekly recommendation telling me the one thing to change, so that I can
# improve my financial behavior with minimal effort.
# AC: one rules-based recommendation/week | considers budget overrun risk, new subscriptions,
#     spending spikes | no meaningful pattern -> neutral/encouraging message, never fabricated advice
#     | no external/bank-sync data required
# Out of scope: ML-personalised recommendations (v1 is rules-based), daily cadence

Feature: Weekly Recommendation Engine

  Scenario: User nearing a budget limit receives a relevant recommendation
    Given I am at 80% of my "Dining" budget with 10 days left in the month
    When my weekly recommendation is generated
    Then it should reference my "Dining" budget specifically
    And it should suggest a concrete action

  Scenario: New user with insufficient data receives a neutral message
    Given I have no transactions yet this week
    When my weekly recommendation is generated
    Then I should see an encouraging onboarding message
    And no fabricated or unsupported claim about my spending should appear

  Scenario: Multiple qualifying triggers in the same week produce one recommendation
    Given I am both over budget in "Dining" and have a newly detected subscription this week
    When my weekly recommendation is generated
    Then I should receive exactly one recommendation, not one per trigger
    And it should be the highest-priority one

  Scenario: Recommendation content is scoped to the authenticated user only
    Given I am authenticated as User A
    When the recommendation engine runs for my account
    Then no data from any other user's account should influence or appear in my recommendation
