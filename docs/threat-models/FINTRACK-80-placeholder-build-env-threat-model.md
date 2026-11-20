# Threat model — FINTRACK-80 reject placeholder values in production build config

**Tier:** Mid-market (story touches OAuth client configuration) · **Date:** 2026-11-20 · **Story:** FINTRACK-80
**Related:** FINTRACK-47 (presence-only guard), live incident 2026-08-30 (`https://placeholder.railway.app` shipped)

## What changed

`apps/web/buildEnvGuard.ts` (pure function, unit-tested) is called from `apps/web/vite.config.ts` when
`command === "build"` only. It fails the build when `VITE_API_BASE_URL` or `VITE_GOOGLE_CLIENT_ID` is
missing **or** matches the FINTRACK-80-AC5 deny-list (trim + lower-case; substring patterns
`placeholder|changeme|your-|example`; whole-value patterns `undefined|null|todo|xxx|""`).

## Trust boundaries

| # | Boundary | Notes |
|---|---|---|
| B1 | CI secret store → build process env | GitHub Secrets supplies the values; the guard is the only check between a mistyped secret and a shipped bundle. |
| B2 | Build process → build log | Build logs are readable by anyone with repo/Actions access (public repo). The error must never carry a value. |
| B3 | Built bundle → end-user browser | Both vars are inlined into public JS. They are not secrets once shipped. |

## Data classification

| Field | Class | Control |
|---|---|---|
| `VITE_API_BASE_URL` | Public (shipped in bundle) | Never echoed in the build error anyway — a mis-pasted value can carry a token (AC2 scenario). |
| `VITE_GOOGLE_CLIENT_ID` | Public (OAuth client id, shipped in bundle) | Same as above. |
| Rejected value (any) | Treat as potentially secret | Error carries variable name + reason only; `BuildConfigError.problems` holds `{key, reason}` only. Tested. |

## Attacker / failure capabilities assumed

Primary threat is **operator error**, not an adversary: a placeholder or template value left in a CI
secret. Secondary: someone with log access harvesting a secret that was pasted into the wrong variable.
**Not** assumed: an attacker who can write CI secrets (they can set any real-looking malicious URL; a
deny-list cannot stop that — B1 integrity is the secret store's job).

## Threats and controls

| ID | Threat | Control | Residual |
|---|---|---|---|
| T1 | Placeholder value ships; all API + OAuth traffic goes to a dead/foreign domain | Deny-list check fails the build | **Medium.** Deny-list only. A wrong-but-real-looking value (typo'd domain) still ships. Post-build smoke test is out of scope (named in the story). |
| T2 | Secret leaked into build logs through the error message | Error names key + reason only; tests assert the value and its token never appear | Low. |
| T3 | Repo's own template value passes the guard | **None.** `apps/web/.env.example` uses `replace-me.apps.googleusercontent.com`, which matches no AC5 pattern | **Medium — flagged to BA.** Copying `.env.example` to `.env` produces a build that passes. AC5 is a fixed list, so Tech Lead did not extend it unilaterally. Recommend a follow-up adding `replace-me` (or changing the template to `your-client-id`). |
| T4 | Guard blocks local dev / tests | Check scoped to `command === "build"`; tested for `serve` in development and test modes | Low. |
| T5 | Over-blocking a legitimate value (e.g. an `example` sub-string in a real host) | By design (BA assumption: reserved example domains rejected). Whole-value patterns don't match inside longer values (tested) | Accepted. |

## Supply chain / SBOM

No new runtime or dev dependency. `package.json` is unchanged. The SBOM gap is a pipeline-level item,
already recorded in the FINTRACK-60 threat model. No new story artefact is needed here.

## Pre-merge checklist

- [x] `vitest run buildEnvGuard.test.ts viteConfigBuildGuard.test.ts`: 25/25 pass
- [x] `tsc -b` clean; changed files lint-clean
- [x] Real `npm run build`: fails on placeholder (exit 1), succeeds with real values (exit 0), value never printed
- [ ] JS SAST (Semgrep/CodeQL) is not wired for `apps/web` in CI. The change has no injection sinks (string compare only); tracked as a pipeline gap
- [ ] Decide T3 (`.env.example` `replace-me`) with BA
