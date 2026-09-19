# ADR-018: Execute the E2E tier in CI, and publish a redacted Allure report

- **Status:** Accepted
- **Date:** 2026-09-11
- **Deciders:** Mr M (tier authority)
- **Raised by:** FINTRACK-65
- **Supersedes nothing.** Relates to ADR-005 (deployment architecture, which
  depends on this repository being public).

## Context

The Playwright suite has existed in `apps/web/e2e/` since the FINTRACK-51
batch and has never been executed. The `test` job names its targets
explicitly — `pytest tests/unit tests/security tests/integration` — and no
job invokes `npx playwright test`. The job installs `@playwright/test` on
every run via `npm install` and then never uses it.

That is worse than having no E2E tier. A suite present in the tree reads as
coverage. During FINTRACK-60 a rewrite of `apps/web/src/main.tsx` deleted the
`VITE_E2E_TEST_MODE` / `__E2E_AUTH_STORE__` seam that `apps/web/e2e/fixtures.ts`
depends on, and CI passed green. It was caught by human review of the PR diff
and restored in `fd7e50b`. A running E2E suite would have failed immediately;
that seam exists for nothing else.

Separately, the audit trail's only evidence of a test run is `ci_run_url`,
pointing at an Actions run whose logs and artifacts expire under the retention
policy. The QA_LEAD envelope schema once carried `allure_report_url` and it
was removed under F-10 as unused. Nothing durable or machine-readable records
what was tested.

## Decision

### 1. Playwright runs on every CI run, report-only at first

A new `e2e` job stands up a real stack — Postgres, Redis, the API under
uvicorn, and the production frontend build served by `vite preview` — and runs
the suite against it. `tests/conftest.py`'s in-memory SQLite and fakeredis are
in-process fixtures; a browser cannot reach them, so the E2E job cannot reuse
the `test` job's wiring.

The job is `continue-on-error: true`. A failing browser test publishes into
the report without failing the build.

This is deliberate and temporary. A browser suite wired up for the first time
is flaky for reasons unrelated to the code under test, and gating on day one
would block every PR on infrastructure teething rather than on defects —
which is how a newly-added E2E tier gets disabled in week two and never comes
back. The flip to blocking is a single word once a week of runs looks stable.

**Consequence, stated plainly:** until that flip, a red E2E run does not stop
a merge. Anyone reading a green build must not take it as evidence the
browser tier passed. The QA_LEAD envelope must continue to report E2E status
separately rather than folding it into the build result.

### 2. Allure results from both layers, merged into one report

`allure-pytest` for the Python suites, `allure-playwright` for E2E, written to
`allure-results/api` and `allure-results/e2e` and merged into a single report
per run.

`allure-pytest-bdd` — which would render pytest-bdd scenarios as Gherkin steps,
genuinely useful for traceability against the BA's feature files — is
deliberately **not** installed. It replaces `allure-pytest` rather than
supplementing it, and both together double-report every test. Switching the
BDD modules over is a separate, deliberate change.

### 3. The report is published to GitHub Pages, redacted

Published from `main` only. Pages serves one site per repository, so
publishing from every branch would have each PR overwrite the last and destroy
the trend history that justifies the work. PR runs still produce results as
artifacts. History is carried forward from the previous publish so trend,
retry and flakiness data accumulates.

**`scripts/trim_allure_results.py` runs before report generation** and strips:

- every attachment file on disk
- every `attachments` list at every nesting depth (test, container, before/after
  fixtures, and steps, which nest arbitrarily)
- `statusDetails.trace` — stack traces
- `statusDetails.message` — assertion messages, replaced with a pointer

It keeps test names, suite structure, status, duration, labels and history ids.

#### Why redaction is required rather than optional

This repository is public, so its Pages site is world-readable and no
authentication is available. A raw Allure report is not a summary: Playwright
attachments are screenshots, videos and traces capturing real request and
response bodies, including `Set-Cookie` headers and bearer tokens minted
during the run. Assertion messages reach the same place by a shorter route — a
failing auth assertion routinely prints the token it compared. These are
test-account credentials rather than production ones, but a public artifact is
not where credentials belong.

The step runs **before** report generation, not after. The generated report
inlines attachment content; redacting afterwards would be too late, and
nothing published to Pages can be unpublished.

#### Why test names are kept

Keeping names is a considered choice. Names publish the security-test
inventory — replay detection, token-type confusion, the rate-limit threshold
and window. But `tests/security/`, `docs/threat-models/` and `docs/adr/` are
already world-readable in this public repo. Redacting names in the report
would hide nothing that is not already one click away, while destroying the
report's value for tracking and audit entirely.

The disclosure redaction actually prevents is runtime material: credentials,
payloads and internal error detail that exist only during a run and appear
nowhere in the source tree. That distinction is the whole basis of this
decision, and it stops holding the moment the repository's visibility changes.

**If this repository is ever made private, revisit this ADR** — Pages on a
private repo requires a paid plan, and the calculus above inverts.

### 4. `allure_report_url` returns to the QA_LEAD envelope

Reinstated alongside `ci_run_url`. F-10 removed it as unused; this makes it
real. `ci_run_url` still cites the run; `allure_report_url` cites the durable
report.

## Alternatives considered

**Publish the full report.** Best debugging experience — every failure
clickable. Rejected: it publishes test-account tokens and full internal error
detail to the open internet, irreversibly.

**Publish the full report to a private repository's Pages.** Keeps fidelity
and access control. Rejected for now: needs a second repository, a cross-repo
deploy token and a paid plan. Worth revisiting if the redacted report proves
too thin to debug from.

**Gate on E2E immediately.** Strongest guarantee, and it would have caught the
`main.tsx` seam deletion. Rejected as the opening move: no baseline exists yet
for what a stable run looks like, so early flakiness would block unrelated
work.

## Consequences

- Every CI run gains a browser-installation and full-stack startup step. The
  `e2e` job is materially slower than `test`. It runs in parallel after `test`
  rather than serially inside it.
- Debugging a published failure requires downloading the run's artifact, since
  the public report carries no trace or message. This is the accepted cost of
  decision 3.
- `scripts/trim_allure_results.py` is security-relevant code. Changes to it
  are changes to what this project publishes, and it must not be moved after
  report generation.
- The E2E specs still do not cover FINTRACK-60. `apps/web/e2e/auth.spec.ts`
  contains nothing about silent refresh, so T3's browser half and T7's
  cross-tab race remain untested even once the harness runs. That work is
  `owner:qa-lead` and is tracked separately from FINTRACK-65.
