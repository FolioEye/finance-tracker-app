# ADR-013: Simple Budget Tracking — Compute-on-Read Monthly Progress

**Status:** Accepted
**Date:** 2026-07-19
**Story:** FINTRACK-20 (Simple Budget Tracking)
**Author:** Tech Lead Agent

## Context

FINTRACK-20 requires a per-category monthly spending limit (AC1) with
progress shown as actual-vs-limit (AC2) that resets each calendar month
(AC3), is editable/removable anytime (AC4), and — for categories with no
budget set — shows spend with no false "over" state (AC5). The story's
own out-of-scope line explicitly excludes rollover budgets and
multi-month planning.

The BA's pass on this story found the pre-existing 4-scenario Gherkin
draft covered only 2 of the 5 ACs (happy-path progress and invalid-limit
validation), and added 4 scenarios to close AC3, AC4, and AC5 -- but left
the "how does the monthly reset actually work" question open for Tech
Lead to answer as an architecture decision, not a BA one.

## Decision

**A) A `Budget` row has no month/year field and is never rewritten or
reset by any scheduled process.** `domain/models/budget.py`,
`domain/repositories/budget_repository.py`, a new `budgets` table
(migration `0005`), and a `SqlAlchemyBudgetRepository` adapter follow the
same port/adapter shape `CategorisationRuleRepository` established --
one evergreen row per `(user_id, category)`, not an append-only history
of monthly snapshots.

**B) "Resets each calendar month" (AC3) is answered by the read side, not
the write side.** `TransactionRepository` gains
`sum_by_category_for_user_in_range(user_id, start_date, end_date)`,
implemented as a single SQL `SUM/GROUP BY` query (pushed down to the DB,
not summed in Python over a full row fetch). The new
`GetBudgetOverviewHandler` (`application/queries/get_budget_overview.py`)
computes `[first-of-this-month, first-of-next-month)` on every call and
passes that range in. Last month's spend simply isn't in the result set
once the calendar rolls over -- there is no batch job, no cron, no
"reset" step that can fail to run, drift, or need a timezone decision
about exactly when midnight-on-the-1st happens for a given user. This is
the same category of decision as ADR-011's staged-import TTL: prefer a
property that's true by construction over a process that has to run
correctly at the right time.

**C) Budget-vs-spend merging happens in one query handler, not two API
calls the frontend has to reconcile.** `GetBudgetOverviewHandler` fetches
both `BudgetRepository.list_for_user()` and the current month's spend
map, then produces one list of `BudgetOverviewItem` covering three cases
in a single pass: a budgeted category with spend, a budgeted category
with zero spend this month (present in the budget list, absent from the
spend map -- treated identically to a zero value), and an unbudgeted
category with spend this month (AC5). The third case is why `budget_id`,
`monthly_limit`, and `percent_used` are all nullable together on
`BudgetOverviewItem`/`BudgetOverviewItemResponse`: a null `monthly_limit`
structurally rules out rendering a percentage or an over/under judgement,
rather than relying on frontend code to remember not to.

**D) Create and edit are distinct operations, not an upsert.** Unlike
FINTRACK-17's `CategorisationRuleRepository.upsert()` (where resubmitting
the same merchant pattern *is* the desired correction UX),
`CreateBudgetHandler` rejects a second `POST` for a category the user
already has a budget for (`BudgetAlreadyExistsError`, mapped to `409`),
directing the caller to `PATCH /api/v1/budgets/{id}` instead. The
Gherkin's AC4 scenarios model "edit an existing budget" and "remove an
existing budget" as their own operations with their own expected
outcomes (recalculated percentage; past spend still visible in
transaction history after removal), which a silent-overwrite `upsert()`
would blur together.

**E) Category matching against transactions is exact-string, not
normalised.** `Transaction.category` is stored exactly as the user typed
it everywhere else in this codebase (no case-folding, no canonical
taxonomy) -- `Budget.category` follows the same convention rather than
introducing normalisation (e.g. upper-casing, the way
`CategorisationRule.merchant_pattern` does) only for this one feature.
Consequence: a budget for `"Groceries"` will not aggregate spend from a
transaction categorised `"groceries"`. This is a known limitation, not an
oversight -- fixing it properly means introducing a canonical category
taxonomy across the whole app, which is out of scope for a 3-point
budgeting story and would affect transactions, imports, and
categorisation rules alike.

**F) The clock is injected, not called inline.** `GetBudgetOverviewHandler`
takes a `clock: Callable[[], date] = date.today` constructor parameter
rather than calling `date.today()` directly in `handle()`. This is what
makes AC3 (month-boundary/reset behaviour) actually testable
deterministically -- QA Lead's tests can pin "today" to, say, the 1st of
a month versus the 28th of the previous one, without depending on
wall-clock time or monkeypatching a module-level function.

## Considered options

- **Per-month `BudgetPeriod` snapshot rows**, created (or lazily
  materialised) at the start of each month, carrying their own
  `spent_amount` counter incremented as transactions are added. Rejected:
  this is exactly the "rollover budgets, multi-month planning"
  infrastructure the story explicitly puts out of scope, and it
  introduces a write-time concern (keeping a denormalised counter in
  sync with the transactions table) for a read that a single indexed
  `GROUP BY` already answers cheaply at this data scale.
- **A scheduled job that zeroes/rotates budget counters at midnight on
  the 1st.** Rejected for the same reason ADR-011 avoided a cleanup job
  for expired staged imports: a process that has to run at the right
  time, in the right timezone, without failing, is strictly more
  operational surface than a query that is correct by construction.
- **Case-insensitive or normalised category matching.** Considered and
  deferred (decision E) -- would require touching `Transaction`,
  `CategorisationRule`, and CSV import all at once to be consistent,
  which is a bigger architectural change than this story's scope
  justifies.

## Consequences

- `TransactionRepository` (the abstract port) gained a new required
  method, `sum_by_category_for_user_in_range`. This is a breaking change
  for any test fixture implementing `TransactionRepository` directly
  (e.g. a `FakeTransactionRepository` used by existing command-handler
  unit tests) -- **any such fixture will now fail to instantiate**
  (`TypeError: Can't instantiate abstract class ... without an
  implementation for abstract method`) until it implements the new
  method. Same mechanical-fixture-update category of breakage ADR-012
  flagged for its own repository-port change; flagged here for QA Lead
  in the same spirit, not a design defect.
- `budgets` table is genuinely new -- no existing story's tests touch it,
  so unlike ADR-012's migration this one shouldn't break any
  *behavioural* assertions elsewhere, only the port-interface breakage
  noted above.
- No new third-party dependencies.

## Verification

Full existing regression suite (`tests/unit`, `tests/security`,
`tests/integration` -- 273 tests) re-run locally after this story's
changes: **273 passed, 0 failed**. Unlike ADR-012's Tech Lead pass, this
one introduced no breaking constructor-signature change to any existing
handler, so there was no fixture fallout to flag -- `TransactionRepository`
gained a new abstract method (see Consequences), but no pre-existing test
in this codebase implements a bespoke `TransactionRepository` fixture
directly against the ABC, so nothing broke in practice. (A future story
that does add such a fixture will need to implement
`sum_by_category_for_user_in_range` on it.)

A throwaway smoke test (create/duplicate-reject/invalid-reject/overview/
edit/delete/IDOR, deleted before QA Lead handoff, not part of the
permanent suite) caught one real bug ahead of QA Lead: `percent_used` was
computed as unquantized `Decimal` division, so `300/500` rendered as the
string `"60.0"` while other inputs could render with many more decimal
places (e.g. any input producing a repeating fraction) -- an inconsistent,
un-contracted API shape. Fixed by quantizing to 2dp (`ROUND_HALF_UP`) in
`get_budget_overview.py`'s `_as_percent()` helper before this ADR was
finalised. See this story's Tech Lead envelope for confirmation this fix
is included. QA Lead's pass is expected to add the real, permanent test
suite for this story's 8 Gherkin scenarios, including a case that would
have caught this (e.g. a non-round spend/limit ratio).
