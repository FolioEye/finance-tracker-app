# FINTRACK-23: Action Follow-Through Tracking — 3pts (Jira key; drafted locally as FINTRACK-012; blocked by FINTRACK-21)
# As a user, I want to mark a recommendation as done or dismissed, so the app can track whether
# I actually act on its advice.
# AC: each recommendation has "Mark as done" / "Dismiss" | status recorded per recommendation |
#     Follow-Through Rate = done / (done+dismissed+ignored) over a rolling window | unactioned past
#     7 days auto-marked "ignored" | feeds back into future recommendation prioritisation
# Out of scope: cross-user aggregate analytics dashboards (internal metrics concern, not user-facing)

Feature: Action Follow-Through Tracking

  Scenario: User marks a recommendation as done
    Given I received a weekly recommendation
    When I mark it "Done"
    Then my Follow-Through Rate should be recalculated to include this action as completed

  Scenario: User dismisses a recommendation
    Given I received a weekly recommendation
    When I mark it "Dismiss"
    Then it should be excluded from my "done" count
    And it should still count toward the Follow-Through Rate denominator

  Scenario: Recommendation goes unactioned past the review window
    Given I received a recommendation 8 days ago and took no action
    When the follow-through check runs
    Then the recommendation should be automatically marked "ignored"

  Scenario: Follow-through records are scoped to the authenticated user only
    Given I am authenticated as User A
    When I request my follow-through history
    Then I should only see records belonging to my own account
