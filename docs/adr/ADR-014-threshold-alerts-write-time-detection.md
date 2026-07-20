# ADR-014: Threshold-Based Alerts — Write-Time Detection + Persisted Alert Table

**Status:** Accepted
**Date:** 2026-07-20
**Story:** FINTRACK-22 (Threshold-Based Alerts)
**Author:** Tech Lead Agent

## Context

FINTRACK-22 needs two kinds of alert: a category crossing a fixed 90% of
its monthly budget (AC1), and a single transaction that's unusually large
relative to the user's own history in that category (AC2), with a
dismiss action (AC4) and a no-spam guarantee -- at most one alert per
crossing (AC5). The BA's pass flagged two open architecture questions
rather than prescribing answers: what "unusually large" means
numerically, and how "no-spam" gets enforced given FINTRACK-20's
established compute-on-read precedent (ADR-013) has no persisted state
to check against. Both were reasoned through with Monty before this pass
began; this ADR records the resulting decisions and why they depart from
ADR-013.

A third, related question -- whether a user justifying a large-transaction
alert should suppress similar future alerts -- was raised during the BA
pass and routed to a PM scope decision rather than answered here. PM's
call (`Fintrack/audit/alert-justification-learning-pm.json`) was GO, but
as its own follow-up story (FINTRACK-25, BACKLOG, depends on this story
shipping first), not folded into this one. Nothing in this ADR forecloses
that future work -- the `alerts` table's `dismissed_at` timestamp is
exactly the hook FINTRACK-25 would extend with a `justification` column
-- but this story ships without it.

## Decision

**A) Alerts are detected at write time, in the presentation layer, not
computed on read.** This is a deliberate break from ADR-013's
compute-on-read precedent for budget overview. The reason isn't
performance -- it's that "fire an alert only once per crossing" (AC5) is
a statement about *events*, not about current state. A pure function of
"spend so far this month" can tell you *that* you're over 90%, but not
whether this is the transaction that pushed you over, versus the fifth
transaction in a row that's already over. Expressing "did this already
happen" requires persisted memory; compute-on-read has none by design.
`EvaluateAlertsForTransactionHandler`
(`application/commands/evaluate_alerts_for_transaction.py`) runs
synchronously after a transaction is created, called from
`transactions.py`'s `create_transaction` endpoint -- composed at the
presentation layer, not inside `CreateTransactionHandler` itself, so a
bug in alert logic can never turn a successful transaction write into a
failed request (see decision E).

**B) A single `alerts` table holds both alert shapes, disambiguated by
`alert_type`.** `domain/models/alert.py` defines one `Alert` dataclass
with `AlertType.THRESHOLD_CROSSING` and `AlertType.LARGE_TRANSACTION`
variants, mirroring the two-factories-one-class pattern
`CategorisationRule` doesn't use but `Budget`/`Transaction` also don't
need (this is the first story with two structurally different reasons
for the same row to exist). A `THRESHOLD_CROSSING` row is keyed by
`(user_id, category, alert_type, period_start, threshold_pct)`; a
`LARGE_TRANSACTION` row is keyed by `transaction_id` alone (globally
unique, so no `user_id` needed in that lookup). Two separate
`UniqueConstraint`s on `alerts` (migration `0006`) enforce both as a
defence-in-depth backstop against a race, with the actual dedup check
happening explicitly in the handler first (see decision D) so a
duplicate never even reaches an `add()` call in the common path.

**C) The large-transaction baseline is a personal rolling average with a
cold-start fallback, not a fixed dollar amount.** A flat threshold (e.g.
"any transaction over $200") would flag routine large purchases for a
high earner and miss real anomalies for a low spender -- the same
one-size-fits-all failure mode a fixed percentage would have. Instead:
`TransactionRepository.get_recent_amounts_for_category()` (new abstract
method, implemented in `SqlAlchemyTransactionRepository`) returns the
user's own last 10 transaction amounts in that category, most-recent
first, excluding the transaction currently being evaluated. A transaction
is "unusually large" if it's at least 3x the average of that history.
Below 3 prior transactions, a personal average is too noisy to trust (a
single $15 coffee would make a $50 lunch "unusually large"), so a flat
$300 fallback baseline applies instead until the user has enough history
in that category. Both constants (`LARGE_TRANSACTION_MULTIPLIER = 3`,
`MIN_SAMPLE_SIZE = 3`, `FALLBACK_BASELINE = $300`,
`ROLLING_WINDOW = 10`) live in
`evaluate_alerts_for_transaction.py` as named module constants, not
buried magic numbers, so a future story tuning them doesn't need to
re-derive the reasoning.

**D) No-spam (AC5) is enforced by an explicit existence check before
`add()`, with the DB unique constraint as backstop, not primary
mechanism.** `_evaluate_threshold_crossing()` calls
`AlertRepository.find_active_threshold_crossing()` for the current
`(user_id, category, period_start, threshold_pct)` before creating a new
row; if one already exists (dismissed or not), no new alert fires. This
is why dismissing an alert does not cause the *same* crossing to
re-fire (AC4 says dismiss must not suppress *future* alerts, which this
satisfies naturally: a new `period_start` next month, or a different
category, has no existing row and so *can* fire fresh -- see the BA's
"dismiss doesn't suppress future alerts" scenario). `_evaluate_large_transaction()`
uses the equivalent `find_by_transaction_id()` check for the same reason.

**E) Alert-evaluation failures are isolated at the call site, not inside
the handler.** `transactions.py`'s `create_transaction` wraps the
`alert_handler.handle(...)` call in a bare `try/except Exception`,
logging `alert_evaluation_failed` and continuing -- the transaction
response is returned regardless of whether alert evaluation succeeded.
This mirrors the constraint matrix's "a bug in a secondary concern must
never break the primary one" principle, applied here because alerts are
explicitly a derived, best-effort signal on top of the transaction
record, not a co-equal write.

**F) The threshold is a single fixed constant (90%), not user-configurable.**
Matches AC1's Gherkin exactly ("crosses 90% of my budget for that
category"), not a multi-tier or per-user-configurable system. FINTRACK-22's
own out-of-scope line lists "custom user-defined thresholds" as P1 --
consistent with keeping `THRESHOLD_PCT = Decimal("90.00")` a plain module
constant for this story rather than a per-`Budget` column that would
currently always hold the same value.

## Considered options

- **Compute-on-read alerts** (re-derive "is this category over 90% right
  now" on every GET, same as ADR-013's budget overview). Rejected: this
  can express *state* ("are we currently over") but not *events* ("did we
  just cross, and have we already told the user"), which is what AC5
  actually requires. A stateless read can't distinguish "still over 90%
  from three transactions ago" from "just crossed 90% right now" without
  external memory -- which is itself a persisted alert record, just
  computed lazily and inconsistently instead of at write time.
- **A flat dollar threshold for "unusually large"** (e.g. any transaction
  over $200, globally). Rejected: no personalisation, and directly
  contradicted by the BA's own scenario framing ("my typical Dining
  transactions are well under $50" implies the bar is relative to the
  user, not absolute).
- **Folding the "justify to suppress future alerts" feedback loop into
  this story**, as originally suggested during the BA pass. Rejected at
  the PM stage (see Context) -- routed to FINTRACK-25 instead, to avoid
  roughly doubling this story's scope and to keep the two-out-of-three-
  competitors-don't-do-this-yet differentiator decoupled from the base
  alert mechanism shipping now.
- **A message queue / background worker for alert evaluation**, decoupling
  it fully from the request/response cycle instead of an in-request
  try/except. Rejected as premature infrastructure for this data scale --
  the try/except isolation in decision E gets the same "never blocks
  transaction creation" guarantee without introducing a queue, worker
  process, or delivery-retry semantics this project doesn't otherwise
  have (no queue exists anywhere else in the codebase yet).

## Consequences

- `TransactionRepository` (the abstract port) gained a new required
  method, `get_recent_amounts_for_category`. Same category of breaking
  change ADR-012 and ADR-013 both flagged for their own port additions --
  any fixture implementing `TransactionRepository` directly (rather than
  via the real SQLAlchemy adapter or a mock) will fail to instantiate
  until it implements the new method. Flagged here for QA Lead in the
  same spirit; not a design defect.
- `alerts` table is genuinely new -- no existing story's tests touch it,
  so this migration shouldn't break any *behavioural* assertions
  elsewhere, only the port-interface breakage noted above.
- `create_transaction`'s response time now includes one additional
  best-effort DB round-trip pair (budget lookup + recent-amounts lookup)
  before returning. Not measured against a production-scale dataset in
  this pass -- flagged as a candidate for follow-up profiling if
  transaction-creation latency becomes a concern, not treated as a
  blocking risk at current data volumes.
- No new third-party dependencies.

## Verification

Full existing regression suite (`tests/unit`, `tests/security`,
`tests/integration` -- 344 tests, the corrected FINTRACK-20 count) re-run
locally after this story's changes: **344 passed, 0 failed**. No existing
handler's constructor signature changed, and no pre-existing test in this
codebase implements a bespoke `TransactionRepository` fixture directly
against the ABC, so the new abstract method caused no fixture fallout in
practice (same situation ADR-013 was in, for the same reason).

A throwaway smoke test (register two users; budget + below-threshold
transaction -> no alert; push spend to 95% -> exactly one threshold
alert; a further same-period transaction -> still exactly one, confirming
no-spam; dismiss -> alert absent from default list, present with
`include_dismissed=true`; three baseline transactions + one 25x-average
transaction in a different, unbudgeted category -> exactly one
large-transaction alert with no budget required; second user attempting
to dismiss the first user's alert -> 404, confirming the IDOR check;
deleted before QA Lead handoff, not part of the permanent suite) passed
end-to-end on the first full run after fixing one test-authoring mistake
(the test's own initial data didn't establish enough transaction history
to escape the cold-start fallback baseline -- not a bug in the
implementation, see decision C). QA Lead's pass is expected to add the
real, permanent test suite for this story's 8 Gherkin scenarios.
