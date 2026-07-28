Feature: Recommendation Prioritisation from Follow-Through Outcomes
  As a user
  I want recommendations that I've consistently ignored or dismissed to stop dominating my weekly recommendation
  So that the app adapts to what I actually act on instead of repeating advice I've shown I won't follow

  Background:
    Given I am authenticated as a registered user
    And FINTRACK-23 has recorded follow-through outcomes for my past recommendations
    And the rolling window for follow-through rate is the last 10 times a recommendation type was shown to me
    And a recommendation type needs at least 3 shown occurrences in the window before it can be deprioritised

  Scenario: A recommendation type I've mostly ignored is deprioritised (AC1)
    Given the recommendation type "dining-out-spike" has been shown to me 10 times in the rolling window
    And I followed through on it 2 of those 10 times (a 20% follow-through rate, below the 30% threshold)
    When my weekly recommendations are generated
    Then "dining-out-spike" recommendations are ranked lower than recommendation types with a follow-through rate at or above 30%

  Scenario: A recommendation type I regularly act on keeps its normal priority (AC1, happy path)
    Given the recommendation type "subscription-price-increase" has been shown to me 10 times in the rolling window
    And I followed through on it 8 of those 10 times (an 80% follow-through rate)
    When my weekly recommendations are generated
    Then "subscription-price-increase" recommendations are ranked at their normal (non-deprioritised) priority

  Scenario: A deprioritised recommendation type recovers as soon as I follow through on it again (AC2)
    Given the recommendation type "dining-out-spike" is currently deprioritised due to a low follow-through rate
    When I follow through on the next "dining-out-spike" recommendation shown to me
    Then "dining-out-spike" immediately returns to normal (non-deprioritised) priority for future recommendations
    And it is not permanently suppressed

  Scenario: Every prioritisation change comes with a plain-language reason (AC3)
    Given the recommendation type "dining-out-spike" has just been deprioritised
    When I view my weekly recommendations
    Then I see a reason attached to the deprioritisation, such as "moved down: ignored 8 of last 10 times"
    And the reason is never a fabricated or generic explanation

  Scenario: Deprioritisation never reorders recommendations across FINTRACK-21's existing trigger tiers (AC4)
    Given a "budget-risk" recommendation and a "subscription-price-increase" recommendation are both due this week
    And "subscription-price-increase" recommendations currently have a high follow-through rate
    And "budget-risk" recommendations currently have a low follow-through rate
    When my weekly recommendations are generated
    Then the "budget-risk" recommendation still ranks above the "subscription-price-increase" recommendation
    And follow-through-based deprioritisation only reorders recommendations within the same trigger tier

  Scenario: A recommendation type with too few occurrences is not yet deprioritised (edge case)
    Given the recommendation type "large-transaction-alert" has only been shown to me 2 times in the rolling window
    And I did not follow through on either occurrence
    When my weekly recommendations are generated
    Then "large-transaction-alert" recommendations keep their normal priority
    And no deprioritisation reason is shown, because the minimum sample size has not been reached

  Scenario: A brand-new recommendation type with no history yet is not deprioritised (negative/edge case)
    Given the recommendation type "new-merchant-detected" has never been shown to me before
    When my weekly recommendations are generated
    Then "new-merchant-detected" recommendations are ranked at normal (non-deprioritised) priority

  Scenario: One user's follow-through history never influences another user's recommendation priority (AC5, security)
    Given user "alice" has a low follow-through rate on "dining-out-spike" recommendations
    And user "bob" has a high follow-through rate on "dining-out-spike" recommendations
    When "bob"'s weekly recommendations are generated
    Then "bob"'s "dining-out-spike" recommendations use only "bob"'s own follow-through history
    And "alice"'s follow-through data is never read, joined, or exposed while computing "bob"'s prioritisation
