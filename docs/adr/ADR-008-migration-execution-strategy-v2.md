# ADR-008: Migration Execution Strategy v2 — Run Alembic in the App Container's Own Entrypoint

## Status
Accepted

## Context

ADR-007's approach (relocate Alembic into `apps/api/`, run it via Railway's
Pre-Deploy Command) was implemented and merged (PR #4), but the Pre-Deploy
Command itself never worked reliably in practice:

1. After setting `DATABASE_URL`'s query string from `sslmode=require` (Neon's
   own default output, standard libpq convention) to `ssl=require` (what
   `asyncpg` actually accepts -- confirmed via direct reproduction: `asyncpg.connect()`
   raises `TypeError: unexpected keyword argument 'sslmode'` immediately,
   before any network attempt), the Pre-Deploy Command kept failing with the
   exact same `sslmode` error.
2. This held true across: editing the value as a Shared Variable reference,
   replacing it with a literal value directly on the service, multiple fresh
   `redeploy` calls, and multiple fresh Railway Console sessions running
   `echo $DATABASE_URL` -- every single one showed `sslmode=require` in the
   live environment despite the saved value being confirmed correct via
   Railway's own Raw Editor.
3. Every one of these failed deployments produced **zero log output** for
   the Pre-Deploy Command step -- not even the "Stopping Container" line
   seen on earlier, different failures. Even a deliberately verbose
   diagnostic command (`echo` + a Python one-liner printing the parsed URL +
   `sleep 5` to rule out a log-flush race) produced nothing.

No further Railway-side lever moved this. This looks like a bug or caching
problem specific to how the Pre-Deploy Command's ephemeral container
resolves environment variables -- not something fixable from our side, and
not something the Pre-Deploy Command's own log stream will ever help us
debug, since it never logs anything on this failure path.

## Decision

**Stop using Railway's Pre-Deploy Command for migrations. Run `alembic
upgrade head` as the first step of the main app container's own
`ENTRYPOINT`, then `exec` into uvicorn.**

```dockerfile
ENTRYPOINT ["sh", "-c", "cd /app/apps/api && python -m alembic upgrade head && exec python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8000"]
```

This uses the exact same container, image, and environment variables as the
app itself (no separate ephemeral container with its own variable
resolution to go wrong), and we already know this container's logs work --
we've seen real "Uvicorn running" output from it before. The `&&` preserves
the same fail-closed guarantee as the Pre-Deploy Command: if migration
fails, uvicorn never starts. `exec` at the end replaces the shell process
with uvicorn (PID 1), preserving correct SIGTERM handling for graceful
shutdowns -- without it, Railway's stop signal would hit the wrapper shell
instead of uvicorn.

ADR-007's decision 1 (Alembic relocated into `apps/api/`) is unchanged and
still required -- this only replaces decision 2 (where the migration runs).

## Consequences

**Positive:** migration and app startup now share one container with one,
already-proven-reliable log stream. No separate Railway dashboard setting
to configure or silently misbehave. Simpler mental model: one container,
one environment, one log stream.

**Negative:** every deploy now pays the migration's latency before the app
starts serving traffic (acceptable at this scale -- one small `CREATE
TABLE`-sized migration so far). If a migration ever fails, the container
exits before binding to a port, so Railway's health check will correctly
mark the deploy as failed -- but there's a brief window with zero replicas
serving if this happens on every replica simultaneously during a redeploy;
worth revisiting with a proper migration-then-swap strategy if this
service ever needs true zero-downtime deploys.

**If Railway's Pre-Deploy Command turns out to work fine on a freshly
created service** (a diagnostic Monty may still run in parallel), that
would suggest the stale-variable behavior was specific to the existing
service object's internal state rather than a platform-wide Pre-Deploy
Command bug -- worth a note here if that's ever confirmed, but doesn't
change this decision either way: running migrations in the app's own
entrypoint is a reasonable, simpler default even without the mystery bug.

## Verification

Plan: same sandbox-simulation approach used for ADR-007 and the original
Dockerfile fix -- reproduce the container's exact filesystem layout,
confirm the `sh -c` entrypoint string resolves `cd /app/apps/api` and runs
`alembic upgrade head --sql` (offline mode) correctly before touching the
real deploy, then push via a proper branch + PR and watch the real Railway
deploy logs (which we can actually see, unlike the Pre-Deploy Command) to
confirm migration output appears and uvicorn starts after it.
