# ADR-015: Envelope & Trail Signing Strategy

**Status:** Accepted
**Date:** 2026-07-20
**Related findings:** F-06 (unsigned/forgeable envelopes, CRITICAL, P1) · F-13 (trail not tamper-evident, HIGH, P1) · ORCH (no runtime enforcement, CRITICAL, P1)
**Author:** Drafted per Monty's request during the 2026-07-20 audit remediation pass
**Lens:** Platform (per the audit's two-speed governance model — feeds the platform P1 roadmap, does not block FinTrack sprints)

## Context

Three findings share one root cause. None of the 27 envelopes or 9 gate-trail
`.jsonl` files carry any signature, hash, or other cryptographic binding —
re-confirmed in the 2026-07-20 audit run (`grep -c hmac|prev_hash` returns 0
across both file types). Concretely, today:

- Any envelope's `status`, `approved_by`, or verdict fields could be
  hand-edited after the fact and nothing would detect it (F-06).
- The trail files are plain-append; a line could be deleted, reordered, or
  inserted with no way to prove the sequence is intact (F-13).
- Nothing runs automatically to check any of this — compliance today is
  voluntary, dependent on whichever stage skill happens to be followed
  faithfully in a given session (ORCH).

An earlier draft of this ADR proposed a two-phase rollout — HMAC now,
asymmetric later. That was revised before adoption, for two reasons worth
recording:

1. **Signing and hash-chaining are orthogonal, not substitutes.** Whichever
   signing scheme is used, it only proves a single envelope or trail line
   wasn't altered after signing — it says nothing about whether that line
   was later deleted, reordered, or had another line inserted around it.
   Only a hash chain (`prev_hash`/`entry_hash`) catches that.
2. **Per-agent asymmetric keys are meaningful even inside one Claude
   session.** The trust boundary that matters isn't "separate OS process"
   — it's "a distinct secret invoked only within that stage's own scope."
   If Tech Lead's private key is only ever used while the Tech Lead skill
   is running, a verifier can confirm a given envelope was signed under
   the Tech Lead identity specifically, without trusting a secret every
   stage shares (HMAC's real weakness). It also means no migration is
   needed later: when a real orchestrator eventually enforces separation
   between agents, the signing scheme underneath doesn't have to change.

## Decision

Adopted **Ed25519 asymmetric signing, per agent identity, plus
hash-chaining the trail — together, in a single phase.**

**A) Per-agent keypairs.** One Ed25519 keypair per agent identity used in
the `agent` field: `PM`, `BA`, `TECH_LEAD`, `QA_LEAD`, `RELEASE_PRO`,
`GATEKEEPER`. Private keys are stored outside this repo, supplied by Monty
at signing time. Public keys are published in `docs/adr/signing_public_keys.json`
alongside this ADR.

**B) Envelope schema addition:** `"signature"` — the hex-encoded Ed25519
signature over the canonicalized envelope JSON (same canonicalization used
for `idempotency_key`: `sort_keys=True, separators=(",", ":")`), covering
every field except `signature` itself.

**C) Trail schema addition:** each `.jsonl` line gains `"prev_hash"`
(SHA-256 of the previous line's raw JSON; a fixed genesis value for a
file's first line) and `"entry_hash"` (SHA-256 of the line's own content,
including `prev_hash`) — a standard hash chain.

**D) Verification:** gatekeeper's Scan 4 verifies signatures against the
public key bundle and confirms the hash chain. No shared secret is ever
needed to verify.

**E) Rollout:** only envelopes and trail entries written from adoption
forward carry these fields. Pre-adoption envelopes/trail lines are a
documented, permanently-unsigned baseline — retroactively signing
historical data wouldn't prove anything about when it was actually
written.

## Consequences

- Six private keys to manage instead of one shared secret; each stage only
  ever touches its own key, so a single key leaking exposes one agent's
  signatures, not the whole trail.
- Needs a small Ed25519 sign/verify helper in whatever runs each stage
  skill — pipeline tooling, not FinTrack application code.
- Public keys are safe to commit in the open (this file's companion,
  `signing_public_keys.json`); private keys must never be.
- The pre-adoption envelopes/trail files stay permanently unsigned by
  design — audit language should reflect "signing adopted 2026-07-20
  forward" rather than counting older unsigned records as a live F-06/F-13
  violation.
