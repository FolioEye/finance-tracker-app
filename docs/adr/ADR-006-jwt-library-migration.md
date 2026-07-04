# ADR-006: JWT Library Migration — python-jose to PyJWT

## Status
Accepted

## Context
A routine security-dependency audit (triggered by Release Pro's Trivy CI gate
failing on PR #2) found real CVEs in `python-jose==3.3.0`
(PYSEC-2024-232/233, PYSEC-2025-185). Bumping to `python-jose==3.4.0` fixes
those, but pulls in `pyasn1==0.4.8` transitively via `python-jose`'s
`rsa`/`ecdsa` dependency -- and `pyasn1==0.4.8` has its own unfixed DoS CVE
(CVE-2026-30922, uncontrolled recursion in ASN.1 decoding). `python-jose==3.4.0`
hard-pins `pyasn1<0.5.0`, so that residual cannot be cleared while python-jose
stays in the stack.

FinTrack's actual JWT usage (see ADR-004) is narrow: HS256 only, symmetric
shared secret, tokens we issue and verify ourselves. We never verify
externally-supplied JWTs, never fetch JWKS, never parse PEM/DER key material
from untrusted input -- i.e. none of the asymmetric-crypto machinery
`python-jose[cryptography]` (and its `rsa`/`ecdsa`/`pyasn1` dependencies) exists
for is actually used.

## Decision
Replace `python-jose[cryptography]` with `PyJWT` in `apps/api/requirements.txt`.
For HS256-only usage, PyJWT's only dependency is `typing_extensions` --
verified in a clean venv: no `pyasn1`, `rsa`, or `ecdsa` anywhere in its
dependency tree. This removes the vulnerable code path entirely rather than
patching around it.

`TokenService`'s public interface (`TokenPair`, `issue_pair(user_id)`) and
claim shape (`sub`, `type`, `iat`, `exp`, `jti`) are unchanged -- this is a
library swap, not a design change. ADR-004's decision to hand-roll JWT
issuance rather than use a managed auth provider still stands.

## Consequences
**Positive:** fully clears the pyasn1 DoS residual; smaller dependency
footprint (1 transitive dependency vs. python-jose's several); PyJWT is the
more widely-adopted library for this exact use case.

**Negative:** one test (`tests/integration/test_register_api.py`) imports
`jose.jwt.get_unverified_claims` directly to inspect token TTL in an
assertion -- swapped to PyJWT's equivalent
(`jwt.decode(token, options={"verify_signature": False})`). No other call
site imports `jose` anywhere in the codebase (verified via search).

**If this changes in the future:** if FinTrack ever needs to verify
externally-issued JWTs (e.g. OAuth/OIDC, a future SSO story), PyJWT also
supports RS256/ES256 verification given a public key -- no library change
needed at that point, just algorithm/key configuration.

## Alternatives considered
- **Pin `pyasn1==0.4.8` and accept the residual:** rejected -- leaves a real,
  known DoS CVE in place indefinitely with no forcing function to revisit it.
- **Keep python-jose, override pyasn1 to 0.6.3 anyway:** attempted and
  rejected -- `pip check` confirms this breaks python-jose's own declared
  constraint (`pyasn1<0.5.0`), an unsupported combination.

## Verification
Full FinTrack test suite (tests/unit, tests/security, tests/integration --
23 tests) run in a real sandboxed venv both before and after this swap:
23/23 passed, 88.2% coverage, identical in both runs. Confirmed via
`pip list` post-install that `jose`, `pyasn1`, `rsa`, and `ecdsa` are no
longer present anywhere in the resolved dependency tree.
