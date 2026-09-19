#!/usr/bin/env python3
"""Redact Allure results before they are published to a PUBLIC GitHub Pages site.

WHY THIS EXISTS
---------------
FolioEye/finance-tracker-app is a public repository, so its Pages site is
world-readable with no authentication available. A raw Allure report is not a
summary -- it embeds attachments, and for Playwright those attachments are
screenshots, videos and traces that capture real request and response bodies,
including Set-Cookie headers and bearer tokens minted during the run. They are
test-account credentials rather than production ones, but they are credentials,
and a public artifact is not the place for them. Assertion messages and
stack traces carry the same risk by a shorter route: a failing auth assertion
routinely prints the token it was comparing.

What this script REMOVES (destructively, in place):
  * every attachment file on disk
  * every `attachments` list, at every nesting depth (test, container,
    before/after fixtures, and steps -- which nest arbitrarily)
  * `statusDetails.trace`  (stack traces)
  * `statusDetails.message` (assertion messages, replaced with a pointer)

What this script KEEPS, deliberately:
  * test names, suite structure, status, duration, labels, history ids

Keeping names is a considered choice, not an oversight. The test source files
themselves -- tests/security/test_refresh_security.py and the rest -- are
already world-readable in this public repo, as are docs/threat-models/ and
docs/adr/. Redacting names in the report would hide nothing that is not
already published one click away, while destroying the report's entire value
for tracking and audit. The incremental disclosure this script prevents is the
runtime material: credentials, payloads and internal error detail that exist
only during a run and appear nowhere in the source tree.

Full-fidelity results, including everything stripped here, remain available in
the run's GitHub Actions artifact, which is access-controlled and subject to
the retention policy.

Raised under FINTRACK-65. Decision recorded in
docs/adr/ADR-018-e2e-execution-and-allure-publishing.md.

Usage:
    python scripts/trim_allure_results.py <allure-results-dir> [...]
"""
from __future__ import annotations

import json
import pathlib
import sys

REDACTED = (
    "[redacted before publication -- see the run's Actions artifact for the "
    "full message, and scripts/trim_allure_results.py for why]"
)

# Allure writes attachments as <uuid>-attachment.<ext>. Playwright's own
# artifacts (traces, videos, screenshots) are referenced from the result JSON
# and land in the same directory, so both patterns are swept.
ATTACHMENT_GLOBS = ("*-attachment*", "*.webm", "*.zip", "*.png", "*.mp4")


def scrub(node):
    """Strip attachments and status detail from a result/container node.

    Recurses through `steps`, `befores` and `afters`, which Allure nests to
    arbitrary depth -- a top-level-only pass leaves attachments behind on any
    test that used a fixture or a nested step, which is most of them.
    """
    if isinstance(node, list):
        for item in node:
            scrub(item)
        return node
    if not isinstance(node, dict):
        return node

    if "attachments" in node:
        node["attachments"] = []

    details = node.get("statusDetails")
    if isinstance(details, dict):
        details.pop("trace", None)
        if details.get("message"):
            details["message"] = REDACTED

    for key in ("steps", "befores", "afters"):
        if key in node:
            scrub(node[key])

    return node


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2

    total_json = 0
    total_files = 0

    for raw in argv[1:]:
        root = pathlib.Path(raw)
        if not root.is_dir():
            print(f"skip (not a directory): {root}")
            continue

        for path in sorted(root.rglob("*.json")):
            # -result.json and -container.json both carry attachments.
            if not path.name.endswith(("-result.json", "-container.json")):
                continue
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                # A malformed result must not silently pass through unredacted.
                print(f"UNPARSEABLE, deleting rather than publishing: {path} ({exc})")
                path.unlink()
                total_files += 1
                continue
            path.write_text(json.dumps(scrub(data)), encoding="utf-8")
            total_json += 1

        for pattern in ATTACHMENT_GLOBS:
            for path in sorted(root.rglob(pattern)):
                if path.is_file():
                    path.unlink()
                    total_files += 1

    print(f"redacted {total_json} result files, deleted {total_files} attachments")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
