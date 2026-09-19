# Threat model — FINTRACK-60 session persistence via silent token refresh

**Tier:** Mid-market (required for any story touching auth, payments or PII)
**Date:** 2026-09-10 · **Story:** FINTRACK-60 · **Related:** ADR-017, ADR-009, ADR-004

## Trust boundaries

| # | Boundary | Crosses | Notes |
|---|---|---|---|
| B1 | Browser ↔ API | `myfintrack.gtech45.com` → `api.gtech45.com` | Same-site after ADR-017, still cross-origin. TLS terminated at Railway edge. |
| B2 | API ↔ Redis | Railway private network | Denylist store. Now availability-critical for sessions. |
| B3 | JS context ↔ cookie jar | Same document | httpOnly is the boundary; script must never read the refresh token. |
| B4 | Attacker page ↔ API | Any origin → `api.gtech45.com` | SameSite=Strict + CORS allowlist are the two controls. |

## Data classification

| Field | Class | Control |
|---|---|---|
| refresh_token | Credential | httpOnly, Secure, SameSite=Strict, `path=/api/v1/auth`, never in a body, never logged, rotated on every use |
| access_token | Credential | Memory only, 15 min, never persisted, never logged |
| jti | Internal | Logged (opaque UUID) |
| user_id / sub | PII (pseudonymous) | Logged as `user_id` only |
| email | PII | Deliberately absent from this endpoint |

## Attacker capabilities assumed

Network attacker on a hostile Wi-Fi; a malicious third-party site the user visits while signed in; an XSS foothold in `apps/web`; a stolen refresh cookie (device theft, backup extraction). **Not** assumed: a compromised API host, or an attacker holding `JWT_SECRET_KEY` — that is total compromise and out of scope for this story.

## Threats and controls (STRIDE)

| ID | Threat | STRIDE | Control | Residual |
|---|---|---|---|---|
| T1 | Stolen refresh token replayed for a new session | Spoofing | Strict rotation + `is_revoked()` check. Second use rejected 401 and logged `refresh_replay_detected` | **Medium.** First use by the thief succeeds; only the *legitimate* user's next attempt reveals the theft. Rotation is detection, not prevention. Accepted — matches OAuth BCP for public clients. |
| T2 | Malicious site silently refreshes the victim's session | Spoofing / CSRF | SameSite=Strict — cookie not sent from another site. CORS blocks reading the response | Low. This is the threat that `SameSite=None` would have opened, and the reason ADR-017 chose the subdomain instead. |
| T3 | XSS exfiltrates the refresh token | Info disclosure | httpOnly cookie, never in a response body (F-02) | Low for the refresh token. **Access token remains exfiltratable by XSS** — inherent to any in-memory-token design; 15-minute lifetime bounds it. |
| T4 | Access token presented at `/refresh` to mint a 7-day session | Elevation | `claims["type"] != "refresh"` → 401 | Low. |
| T5 | Refresh endpoint brute-forced or used as a Redis-write amplifier | DoS | Rate limited 5/15 min per IP, same budget as login | Medium. IP-keyed, so a botnet spreads across it. Same limitation login already carries. |
| T6 | Redis unavailable → denylist unreadable | DoS | `is_revoked()` raises → refresh fails → 401 → user re-authenticates | Accepted. Fails **closed**. Redis is now session-critical; belongs in FINTRACK-64 alerting. |
| T7 | Rotation race logs out an innocent user | DoS (self-inflicted) | Shared in-flight promise per document | Medium across separate tabs. Accepted in ADR-017 — a grace window would defeat T1's detection. |
| T8 | Token issued for a deleted/deactivated user | Elevation | **None.** No DB check on the refresh path | **Medium — accepted, flagged.** A deactivated user keeps refreshing for up to 7 days. See below. |
| T9 | Refresh cookie sent to an unintended path | Info disclosure | `path=/api/v1/auth` scopes it away from every business endpoint | Low. |
| T10 | Token replay after logout | Spoofing | Logout already denylists the `jti`; `/refresh` now reads that denylist | Low. **Improved by this story** — logout's revocation had no reader before now. |

## T8 — the one accepted gap worth naming

`RefreshSessionHandler` deliberately takes no DB session: validity is derived from the token signature plus the denylist. This keeps refresh fast and Postgres-independent, but means **deactivating a user does not end their existing session** — they refresh successfully until the 7-day token expires.

Not in scope for FINTRACK-60, whose ACs cover session persistence, not session revocation, and adding a per-refresh user lookup would put Postgres on the auth hot path — a real performance and availability cost for a threat the product cannot currently exercise (there is no deactivation UI). Recorded here rather than silently omitted. If a "deactivate user" or "sign out everywhere" feature is ever built, it must revoke the refresh `jti` at that moment, and this row should be revisited.

## Pre-merge checklist

- [ ] `bandit -r apps/api` clean (SME+ SAST gate; Mid-market adds SBOM, does not replace bandit)
- [ ] No token value in any log line — grep the diff for `refresh_token`, `access_token` near `logger`
- [ ] Cookie attributes byte-identical across `/register`, `/login`, `/oauth/*`, `/refresh`
- [ ] `refresh_replay_detected` wired into alerting (FINTRACK-64)
- [ ] Confirm in DevTools that a real login now *stores* a cookie for `api.gtech45.com` — the decisive test per ADR-017

## SBOM (Mid-market, SLSA Build L2 target)

This story adds **no new dependency** — it uses PyJWT, redis-py, FastAPI, zustand and TanStack Query, all already pinned. The SBOM requirement is therefore a build-pipeline gap, not a story-scoped artifact, and is best met by adding generation to CI rather than committing a hand-made file that goes stale immediately:

```yaml
- name: Generate SBOM (CycloneDX)
  run: |
    pip install cyclonedx-bom
    cyclonedx-py requirements apps/api/requirements.txt -o sbom-api.json
    npm --prefix apps/web ci
    npx --prefix apps/web @cyclonedx/cyclonedx-npm --output-file sbom-web.json
- name: Scan dependencies
  run: |
    pip install pip-audit && pip-audit -r apps/api/requirements.txt
    npm --prefix apps/web audit --audit-level=high
- uses: actions/upload-artifact@v4
  with:
    name: sbom
    path: sbom-*.json
```

Signing the SBOM and attaching provenance is the remaining SLSA L2 step and belongs with Release Pro, who owns the CI workflow — flagging it here so it is not assumed done. Recommend it be tracked as its own story alongside FINTRACK-63/64 rather than bolted onto this one.
