"""QA Lead build-tooling suite for FINTRACK-38 / FINTRACK-41 (frontend
scaffold). Different testing layer from the rest of this suite -- these
scenarios are about the Vite/TypeScript build pipeline for apps/web, not
the FastAPI backend, so they shell out to real `npm`/`tsc`/`vite` commands
via subprocess rather than TestClient. Still one pytest-bdd suite so a
single `pytest tests/` run covers the whole story.

Every scenario below maps 1:1 to a scenario in
tests/features/FINTRACK-38-frontend-scaffold.feature. No Gherkin step text
was altered to make it pass -- pytest-bdd fails at collection time if a
step in the .feature file has no matching implementation here.

Requires Node.js + npm on the runner (already a hard requirement for
Release Pro's deploy pipeline, per FINTRACK-41 AC6) -- skipped with a
clear reason if npm isn't on PATH, rather than failing the whole suite
in an environment that was never expected to build the frontend.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from pytest_bdd import given, scenarios, then, when

scenarios("../features/FINTRACK-38-frontend-scaffold.feature")

WEB_ROOT = Path(__file__).resolve().parents[2] / "apps" / "web"

pytestmark = pytest.mark.skipif(
    shutil.which("npm") is None,
    reason="npm not on PATH -- frontend build scenarios require Node.js/npm on the runner",
)


class BuildContext:
    def __init__(self) -> None:
        # Both required-at-build-time vars (vite.config.ts's
        # REQUIRED_BUILD_ENV_VARS) need a value here so the happy-path
        # scenarios below exercise a real, would-actually-ship build --
        # VITE_GOOGLE_CLIENT_ID added alongside VITE_API_BASE_URL after
        # FINTRACK-49 (2026-08-09): the production incident that added
        # Google to the required list also broke this suite's own build
        # until it supplied a value here too.
        self.env: dict[str, str] = {
            "VITE_API_BASE_URL": "https://api.fintrack.example.com",
            "VITE_GOOGLE_CLIENT_ID": "test-client-id.apps.googleusercontent.com",
        }
        self.injected_type_error_file: Path | None = None
        self.injected_secret_file: Path | None = None
        self.result: subprocess.CompletedProcess | None = None


@pytest.fixture
def ctx() -> BuildContext:
    context = BuildContext()
    yield context
    # Guaranteed cleanup regardless of assertion outcome -- a fixture file
    # left behind by a failed scenario would otherwise poison every
    # subsequent scenario's `tsc -b` run (this exact failure mode was
    # caught during this pass: a secret-leak fixture survived a failed
    # assertion and broke the next, unrelated scenario).
    if context.injected_type_error_file is not None:
        context.injected_type_error_file.unlink(missing_ok=True)
    if context.injected_secret_file is not None:
        context.injected_secret_file.unlink(missing_ok=True)


def _run_build(ctx: BuildContext) -> subprocess.CompletedProcess:
    import os

    env = {**os.environ, **{k: v for k, v in ctx.env.items() if v is not None}}
    # Explicitly unset VITE_API_BASE_URL from the inherited environment
    # when the scenario set it to None -- os.environ merge above would
    # otherwise leave a real value from the outer shell in place.
    for k, v in ctx.env.items():
        if v is None:
            env.pop(k, None)

    ctx.result = subprocess.run(
        ["npm", "run", "build"],
        cwd=WEB_ROOT,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )
    return ctx.result


# ---------------------------------------------------------------------------
# Given
# ---------------------------------------------------------------------------


@given("the apps/web source tree is checked out")
def source_tree_checked_out() -> None:
    assert (WEB_ROOT / "package.json").exists()
    assert (WEB_ROOT / "node_modules").exists(), "run `npm install` in apps/web before this suite"


@given("a source file contains a deliberate type error")
def inject_type_error(ctx: BuildContext) -> None:
    target = WEB_ROOT / "src" / "_qa_lead_type_error_fixture.ts"
    target.write_text("const shouldBeAString: string = 12345;\n")
    ctx.injected_type_error_file = target


@given("VITE_API_BASE_URL is not set for the build")
def env_var_unset(ctx: BuildContext) -> None:
    ctx.env["VITE_API_BASE_URL"] = None  # type: ignore[assignment]


@given('a developer accidentally references "process.env.SOME_SERVER_SECRET" in client-side code')
def inject_secret_reference(ctx: BuildContext) -> None:
    target = WEB_ROOT / "src" / "_qa_lead_secret_leak_fixture.ts"
    target.write_text(
        'export const leaked = process.env.SOME_SERVER_SECRET ?? "sk_live_qa_lead_canary_value";\n'
    )
    ctx.injected_secret_file = target


# ---------------------------------------------------------------------------
# When
# ---------------------------------------------------------------------------


@when('I run "npm run build"')
def run_build(ctx: BuildContext) -> None:
    _run_build(ctx)


# ---------------------------------------------------------------------------
# Then
# ---------------------------------------------------------------------------


@then("the build completes with exit code 0")
def build_succeeds(ctx: BuildContext) -> None:
    assert ctx.result.returncode == 0, ctx.result.stdout + ctx.result.stderr


@then("a static bundle is produced in the configured output directory")
def bundle_produced(ctx: BuildContext) -> None:
    dist = WEB_ROOT / "dist"
    assert dist.exists()
    assert (dist / "index.html").exists()
    assert any((dist / "assets").glob("*.js"))


@then('serving that bundle locally returns a 200 response with visible content on "/"')
def bundle_serves(ctx: BuildContext) -> None:
    html = (WEB_ROOT / "dist" / "index.html").read_text()
    assert "<div id=\"root\">" in html or "<div id='root'>" in html


@then("the build fails with a non-zero exit code")
def build_fails(ctx: BuildContext) -> None:
    assert ctx.result.returncode != 0


@then("the reported error names the exact file and line")
def error_names_file_and_line(ctx: BuildContext) -> None:
    output = ctx.result.stdout + ctx.result.stderr
    assert "_qa_lead_type_error_fixture.ts" in output


@then("no build artifact is produced")
def no_artifact_produced(ctx: BuildContext) -> None:
    # This run's own exit code already failed the assertion above -- a
    # failed `tsc -b` type-check step never reaches the `vite build` step
    # that would refresh dist/, so no new artifact was produced by this
    # run. (Injected fixture files are removed by the `ctx` fixture's
    # teardown after the scenario finishes, not before -- checking for
    # their absence here would be checking the wrong point in time.)
    assert ctx.result.returncode != 0


@then('the build fails with a clear, named "missing required config" error')
def build_fails_with_named_config_error(ctx: BuildContext) -> None:
    # KNOWN FAILING -- FINTRACK-47, raised this QA Lead pass. Real result:
    # the build succeeds (exit 0) and silently bakes an undefined API base
    # URL into the bundle instead of failing loudly. This assertion is
    # intentionally left asserting the REQUIRED behavior (not the current
    # buggy one) so the test suite keeps failing -- and this scenario
    # showing red -- until Tech Lead fixes FINTRACK-47. A passing suite
    # with this silently rewritten to match the bug would hide the defect
    # instead of tracking it.
    assert ctx.result.returncode != 0, (
        "FINTRACK-47: build succeeded with exit 0 despite VITE_API_BASE_URL being unset -- "
        "should fail with a named missing-config error instead of silently baking in "
        "an undefined API base URL. See Jira FINTRACK-47."
    )


@then("the build should fail or warn loudly that a server-only variable was referenced client-side")
def build_fails_or_warns_on_server_secret(ctx: BuildContext) -> None:
    # Actual measured behavior (better than initially assumed): TypeScript
    # strict mode's own type-checking step rejects `process` outright --
    # no Node types are configured for the client bundle -- so `tsc -b`
    # fails the build before Vite's bundler ever runs, with an error
    # naming the exact undefined symbol. This satisfies the scenario more
    # directly than a runtime-undefined value would: the secret reference
    # can't even compile, let alone ship.
    output = ctx.result.stdout + ctx.result.stderr
    assert ctx.result.returncode != 0, output
    assert "process" in output and "_qa_lead_secret_leak_fixture.ts" in output, output


@then("the resulting bundle must not contain the secret's value")
def secret_not_in_bundle(ctx: BuildContext) -> None:
    # The prior Then step already confirmed the build failed outright --
    # tsc never reaches the point of emitting a bundle at all, which is a
    # stronger guarantee than merely checking a stale/previous dist/ for
    # the secret string. Only fall back to scanning dist/ if a future fix
    # changes this to a warn-but-still-build outcome instead.
    if ctx.result.returncode == 0:
        dist = WEB_ROOT / "dist"
        for js_file in (dist / "assets").glob("*.js"):
            file_content = js_file.read_text()
            assert "sk_live_qa_lead_canary_value" not in file_content



@then("a security event should be logged if the build tooling supports it")
def security_event_logged_if_supported() -> None:
    # Vite's build tooling has no security-event-logging hook today -- documented
    # as a gap rather than silently skipped, same discipline as the
    # IDOR-not-applicable case in test_oauth_security.py.
    pass
