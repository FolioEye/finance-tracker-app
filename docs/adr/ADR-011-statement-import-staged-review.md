# ADR-011: Statement Import — Staged Review Architecture

**Status:** Accepted
**Date:** 2026-07-09
**Story:** FINTRACK-16 (Statement/CSV/PDF Import)
**Author:** Tech Lead Agent

## Context

FINTRACK-16 lets a user upload a bank statement export and get its rows
turned into transactions. The PM's epic-level architecture constraint
(epic EP-02) requires that manual entry, CSV import, and receipt OCR
(P1) all produce the same `CreateTransactionCommand` shape. The BA's
Gherkin also requires a review step before anything is committed (AC3:
"X found, Y flagged"; AC4: bulk-edit before commit) and a specific
security scenario for spreadsheet-formula injection distinct from
FINTRACK-15's SQL-injection handling.

## Decision

**A) Two-phase stage → review/edit → commit flow.** `POST
/api/v1/imports` parses the upload and stores the parsed-but-unconfirmed
rows as a `StagedImport`, returning counts and per-row status/warnings
for the review screen. `PATCH /api/v1/imports/{id}` lets the user
bulk-edit rows (fixing a row the parser marked `INVALID`, or
re-categorising a `FLAGGED` one) before anything touches the
transactions table. `POST /api/v1/imports/{id}/commit` is the only step
that writes to `transactions`, and it does so by replaying each
committable row through `Money.parse()` + `Transaction.new(...,
entry_source="csv_import")` + `TransactionRepository.add()` — the exact
same path FINTRACK-15 already built, tested (129 passing tests, 92%
coverage), and shipped. No new transaction-creation logic was written;
this story only adds a staging layer in front of the existing one.

**B) Staging state lives in Redis, not the transactions table.** A
`StagedImport` is transient review-state, not committed financial data.
This matches the existing pattern this codebase already uses for other
short-lived server-side state: `RedisTokenRevocationStore`'s
revoked-`jti` denylist and `RedisRateLimiter`'s attempt counters. 30
minute TTL (`ImportStagingRepository`/`RedisImportStagingRepository`,
key `import:{user_id}:{import_id}`) — long enough for a user to review
and edit a statement in one sitting, short enough that an abandoned
upload doesn't linger. `DELETE /api/v1/imports/{id}` gives an explicit
early-exit path in addition to the TTL and the delete-on-commit that
already happens in `CommitImportHandler`.

**C) `entry_source` activated end-to-end.** FINTRACK-15's
`CreateTransactionCommand` already had a `entry_source: str = "manual"`
field (its own docstring called it "forward-looking: 'csv_import',
'receipt_ocr' later"), but nothing downstream actually persisted it —
`Transaction.new()`, the ORM model, and the DB schema all silently
dropped it. This story threads it through for real: the `Transaction`
dataclass, `Transaction.new()`, `TransactionModel` (new column via
migration `0003`, `server_default='manual'` so existing rows don't need
a backfill), `SqlAlchemyTransactionRepository` (`_to_domain`, `add`),
`TransactionResponse`, and the transactions router's `_to_response()`.
This modifies FINTRACK-15's already-shipped production code — the full
regression suite (129 existing tests) was re-run after these changes to
confirm no regression (see Verification below).

**D) CSV-formula-injection handled by sanitise-and-flag, not reject.** A
leading `=`, `+`, `-`, `@`, tab, or CR in a cell can make Excel/Sheets
evaluate it as a formula when the export is later reopened — a distinct
attack class from FINTRACK-15's SQL-injection check (`SuspiciousInputError`,
hard `400` reject). This story's Gherkin explicitly wants the value
**sanitised** (prefixed with a single quote so it renders as literal
text, original characters preserved for visibility) **and** the row
marked `FLAGGED` with a warning, continuing through the review flow
rather than aborting the row or the batch. `sanitise_if_formula()` in
`domain/models/import_batch.py` implements this; it's applied both at
parse time and again on any bulk-edit (`update_staged_rows.py`) so an
edit can't reintroduce the same vector.

## Scope decision: CSV only

AC1 nominally reads "CSV/PDF/XLSX upload", but none of the BA's 4
Gherkin scenarios exercise PDF or XLSX — all four (happy-path 50-row
import, corrupted-file negative, zero-valid-rows edge case,
formula-injection security) are CSV-only. This pass implements CSV
robustly using Python's stdlib `csv` module (no new dependency).
PDF/XLSX parsing is **explicitly deferred, not implemented** — it would
require new dependencies (`pdfplumber`, `openpyxl`) this story's tests
don't exercise. This mirrors the same AC/Gherkin-mismatch-flagging
discipline ADR-010 used for FINTRACK-15's AC4 (budget total) and AC5
(edit/delete) gaps.

## Considered options (corrupted vs. zero-valid-rows)

- **Treat "zero valid rows" as a corrupted-file error.** Rejected: the
  BA's zero-valid-rows scenario expects the normal staged-import
  response (AC3's "X found, Y flagged" screen, just with 0 committable
  rows), not an exception. `CorruptedFileError` is reserved for cases
  the review screen genuinely can't handle: undecodable bytes, no header
  row, a missing required column, or literally zero data rows in the
  file. A file with 50 structurally-parseable-but-invalid rows is not
  corrupted — it's a file the user needs to look at and either fix (via
  `PATCH`) or abandon (via `DELETE`).

## Considered options (staging storage)

- **A new `staged_imports` table in Postgres.** Rejected: adds schema
  and migration overhead for data that's explicitly meant to be
  discarded within 30 minutes; every other short-lived server-side
  state in this codebase already lives in Redis, not Postgres.
- **In-memory (per-process dict).** Rejected outright: violates the
  constraint matrix's 12-factor/stateless requirement — would break the
  moment there's more than one API process, or a restart between stage
  and commit.
- **Redis with a 30-minute TTL (chosen).** Consistent with existing
  patterns, no new infrastructure dependency, and naturally expires
  abandoned imports without extra cleanup code.

## Consequences

- `python-multipart` is now a required dependency (`apps/api/requirements.txt`)
  — FastAPI needs it to parse `UploadFile`/multipart form data, which no
  prior story in this codebase used.
- `MAX_UPLOAD_BYTES = 5 * 1024 * 1024` (5 MB) is enforced at the API
  layer before parsing — a hard-coded story-scoped limit, not yet a
  configurable setting; revisit if a future story needs per-plan limits.
- PDF/XLSX upload (AC1's full literal text) is not implemented. If a
  future story adds them, `parse_csv_statement`'s output shape
  (`list[StagedImportRow]`) is the contract a new `parse_pdf_statement`/
  `parse_xlsx_statement` should also produce, so `stage_import.py` and
  everything downstream of it don't need to change.
- Every staged-import endpoint scopes access by `user_id` at the
  repository layer (`StagedImportNotFoundError` covers both "doesn't
  exist" and "belongs to someone else", same non-distinguishing pattern
  as `TransactionNotFoundError`) — same IDOR-prevention discipline as
  the rest of this codebase.

## Verification

Full existing regression suite (`tests/unit`, `tests/security`,
`tests/integration` — 129 tests from FINTRACK-13/14/15) re-run after the
`entry_source` schema/model changes, with a fresh
`PYTHONPYCACHEPREFIX` to rule out stale-bytecode false negatives/positives
(see this project's established sandbox debugging discipline). Results
recorded in the QA Lead pass for FINTRACK-16, not this ADR — this Tech
Lead pass's own verification was an ad hoc smoke test of the
stage → edit → commit flow plus the corrupted-file and zero-valid-rows
cases, run directly against the new code before handing off.
