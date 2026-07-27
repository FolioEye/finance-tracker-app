# FINTRACK-23: Action Follow-Through Tracking — 3pts (Jira key; drafted locally as FINTRACK-012; blocked by FINTRACK-21)
# As a user, I want to mark a recommendation as done or dismissed, so the app can track whether
# I actually act on its advice.
# AC: each recommendation has "Mark as done" / "Dismiss" | status recorded per recommendation |
#     Follow-Through Rate = done / (done+dismissed+ignored) over a rolling window | unactioned past
#     7 days auto-marked "ignored" | outcome recorded for a future prioritisation feature to
#     consume (FINTRACK-27 owns the consumption logic, split out 2026-07-27)
# Out of scope: cross-user aggregate analytics dashboards (internal metrics concern, not
#     user-facing); recommendation-prioritisation logic (split out as FINTRACK-27)
#
# BA note (2026-07-27): expanded from the original 4-scenario draft to 7 -- added a
# negative/validation scenario, an action-specific IDOR scenario (distinct from the read-scoping
# scenario already present), and a scenario actually exercising AC3's Follow-Through Rate formula.

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

  Scenario: Attempt to submit an invalid action value
    Given I received a weekly recommendation
    When I submit an action value of "delete" instead of "done" or "dismiss"
    Then I should see validation error "Invalid action value"
    And no follow-through status should be recorded or changed

  Scenario: Attempt to mark another user's recommendation as done
    Given I am authenticated as User A
    And User B has a recommendation with a known record id
    When I attempt to mark User B's recommendation record as "Done" using its record id
    Then the request should be rejected
    And User B's follow-through record should remain unchanged

  Scenario: Follow-Through Rate reflects a mix of done, dismissed, and ignored actions
    Given over the rolling window I have 2 recommendations marked "Done", 1 marked "Dismiss", and 1 marked "Ignored"
    When my Follow-Through Rate is calculated
    Then it should equal "50%"
