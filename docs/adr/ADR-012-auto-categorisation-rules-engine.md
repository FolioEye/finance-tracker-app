# ADR-012: AI Auto-Categorisation — Rules Engine Architecture

**Status:** Accepted
**Date:** 2026-07-16
**Story:** FINTRACK-17 (AI Auto-Categorisation Rules Engine)
**Author:** Tech Lead Agent

## Context

FINTRACK-17 requires imported (and, per AC4, potentially manual) transactions
to be automatically categorised by pattern-matching merchant/description text
against a per-user rules table (AC1), falling back to "Uncategorised" rather
than a low-confidence guess when nothing matches (AC2). The BA's Gherkin also
requires the match to be auditable (AC6, "see which rule produced the
match"), a review-screen summary before commit (AC5, "X of Y
auto-categorised, Z need review"), a direct rule-creation path with its own
SQL-injection security scenario, and — the gap the BA's pass on this story
found and closed with a 5th scenario — a correction-feedback loop where
fixing an imported transaction's category creates a personal rule for next
time (AC3).

## Decision

**A) `CategorisationRule` is a new domain model, not an extension of
`Transaction`.** A rule (`merchant_pattern` -> `category`, scoped to
`user_id`) is a distinct, independently-persisted concept from a
transaction — `domain/models/categorisation_rule.py`,
`domain/repositories/categorisation_rule_repository.py`, a new
`categorisation_rules` table (migration `0004`), and a
`SqlAlchemyCategorisationRuleRepository` adapter, following the exact same
port/adapter shape `TransactionRepository` already established.

**B) Matching is case-insensitive substring, not exact match or ML.**
`find_matching_rule()` upper-cases both the rule's pattern and the
transaction's description and checks `pattern in description` — "STARBUCKS"
matches "STARBUCKS #4521" because bank exports append store numbers/locations
to the base merchant name. Multiple matches are resolved by longest-pattern-
wins (most specific), tie-broken by earliest `created_at` for determinism.
Explicitly rules-based, not a trained model, per the PM's "rules engine"
framing and AC's explicit out-of-scope note.

**C) The matching pass is a post-processing step in `StageImportHandler`,
not a change to `parse_csv_statement()`.** ADR-011 established
`parse_csv_statement()` as a pure parsing function; this story adds
`apply_auto_categorisation(rows, rules)` in `domain/models/import_batch.py`
as a separate domain function, called by `StageImportHandler` after parsing
and after fetching the user's rules. This keeps the CSV-structural-parsing
concern and the categorisation concern independently testable and
independently reasoned about, consistent with the layering discipline this
codebase already uses (`sanitise_if_formula` is similarly a separate concern
from date/amount validation).

**D) A rule match — or its absence — is now authoritative for an imported
row's category, superseding the CSV's own category/type column.** This is a
deliberate behaviour change from FINTRACK-16, and a security-relevant one:
previously, `parse_csv_statement()` used the CSV's own `category`/`type`
column as the row's category (falling back to "Uncategorised" only when that
column was absent). The BA's Gherkin scenario 2 is explicit that an unmatched
merchant must show "Uncategorised" regardless — a "keep the CSV's column as a
fallback" design would silently contradict that whenever the column happened
to be populated. Consequence (see Verification below): the CSV's category
column is no longer trusted as transaction data at all once a rule pass runs
over it, which closes off — rather than opens — a category-column injection
surface: SQLi/XSS-shaped content placed in that column can no longer reach
`Transaction.new()` as a category value, because it's never used as one.

**E) The correction-feedback loop lives in `UpdateTransactionHandler`, gated
on `entry_source == "csv_import"`.** Editing a transaction's category away
from "Uncategorised" now upserts a `CategorisationRule` mapping that
transaction's `note` (verbatim, not fuzzy-extracted) to the new category —
AC3 / Gherkin scenario 5. Scoped to imported transactions specifically,
matching the Gherkin's literal "an imported transaction ... was left
Uncategorised" framing; manual entries can't actually reach "Uncategorised"
under FINTRACK-15's existing AC2 (category is required there), so the guard
is precise rather than defensive-but-vacuous.

**F) One `upsert()` method serves both rule-creation paths.** Direct rule
creation (`POST /api/v1/categorisation-rules`) and the correction-feedback
loop are the same underlying operation — "this user maps this merchant to
this category from now on" — so `CategorisationRuleRepository.upsert()` is
shared by both rather than the codebase carrying two near-identical
create-or-update paths. A second submission for the same normalised
`merchant_pattern` updates the existing rule's category rather than creating
a silent duplicate the matching engine would have to disambiguate between
(`UniqueConstraint(user_id, merchant_pattern)` at the DB layer backs this).

**G) Security validation reuses `SuspiciousInputError`, not a new exception
type.** The direct-creation endpoint's injection scenario uses the same
SQLi-shaped-pattern check and exception type FINTRACK-13/14/15/16 already
established, so tests and callers share one vocabulary for this class of
rejection rather than this story inventing a parallel one.

## Considered options (where should auto-categorisation apply)

- **Also auto-categorise manual entries with a blank category.** Rejected
  for this pass: FINTRACK-15's AC2 makes category a required field on manual
  entry, and none of this story's 5 Gherkin scenarios exercise a manual-entry
  auto-categorisation path. AC4 ("works on manual+imported... no bank-sync")
  is read here as a scoping/negative constraint (ruling out bank-sync), not a
  requirement to change FINTRACK-15's required-category behaviour. Flagged as
  a gap if a future story wants manual entries to support an optional/blank
  category with auto-suggestion.
- **List/delete endpoints for a user's rule set.** Not implemented — no
  Gherkin scenario tests listing or deleting rules, only creating one and the
  correction-feedback upsert. Deferred, same AC/Gherkin-mismatch-flagging
  discipline ADR-010/011 used for their own deferred scope.

## Consequences

- No new dependencies — `categorisation_rule.py`'s SQLi check duplicates
  (rather than imports) `transaction.py`'s private regex, matching this
  codebase's existing precedent of each domain module owning its own
  validation (`import_batch.py`'s `sanitise_if_formula` alongside
  `transaction.py`'s SQLi check is the same pattern).
- `StageImportHandler` and `UpdateTransactionHandler` both gained a required
  `categorisation_rule_repository` constructor parameter. This is a breaking
  change to their existing call sites in `tests/unit/test_import_command_handlers.py`,
  `tests/unit/test_transaction_handlers.py`, and two fixtures in
  `tests/integration/test_imports_api.py` that construct `StageImportHandler`
  directly against the real Redis repository. **19 pre-existing tests now
  fail with `TypeError: missing 1 required positional argument`** — a
  mechanical fixture update (add a `FakeCategorisationRuleRepository`,
  matching the existing `FakeTransactionRepository`/`FakeImportStagingRepository`
  pattern), not a design defect. Flagged for QA Lead.
- **3 pre-existing security tests in `tests/security/test_imports_security.py`
  now fail** because of decision (D) above: `test_sql_injection_in_csv_category_is_skipped_at_commit_not_committed`,
  `test_security_event_is_logged_on_csv_row_sql_injection_attempt`, and
  `test_xss_payload_in_csv_category_is_stored_as_inert_text_not_executed` all
  planted their payload in the CSV's `category` column and asserted on what
  happened when that column's value reached `Transaction.new()`. It no longer
  does — the row commits with category `"Uncategorised"` (no rule matches a
  benign description like "Normal purchase"), so the payload is discarded
  before it ever becomes transaction data, rather than being rejected and
  skipped at commit. This is a stronger security guarantee than before, not a
  weaker one, but it invalidates these tests' literal assertions. Flagged for
  QA Lead to rewrite against the new behaviour rather than treat as a
  regression to revert.
- `CategorisationRuleModel.merchant_pattern` is `String(255)` — generous
  headroom over `Transaction.note`'s `String(500)` source data, since a
  merchant pattern is typically a short prefix/substring of a full
  description, not the whole thing.

## Verification

Full existing regression suite (`tests/unit`, `tests/security`,
`tests/integration` — 215 tests from FINTRACK-13/14/15/16) re-run after this
story's changes. **193 passed, 22 failed** — all 22 failures map to the two
causes documented above (19 constructor-signature, 3 behavioural), each
traced to its root cause and none representing an unexplained regression.
This Tech Lead pass's own verification was a syntax/compile check
(`ast.parse`) on every new/modified file plus this full-suite run; QA Lead's
pass is expected to update the 19 fixture call sites, rewrite the 3
category-column security tests against the new behaviour, and add new
tests for this story's own 5 Gherkin scenarios.
