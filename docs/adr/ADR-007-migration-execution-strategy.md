# ADR-007: Migration Execution Strategy — Relocate Alembic, Use Railway Pre-Deploy Command

## Status
Accepted

## Context
The app has been deploying and starting successfully on Railway (after the
Dockerfile and environment-variable fixes), but the Neon Console's Tables
view showed **0 tables in the `public` schema** — Alembic migrations had
never actually been applied to the real production database. Investigating
why revealed two compounding problems:

1. `alembic.ini` and the `alembic/` folder (`env.py` +
   `versions/0001_create_users_table.py`) live at the repo root
   (`Fintrack/Code/`), not inside `apps/api/`.
2. Railway's build context for the `finance-tracker-app` service is scoped
   to `apps/api/` (confirmed via the real Railway build log during the
   earlier Dockerfile fix — `COPY requirements.txt .` only succeeds if the
   build context starts inside `apps/api/`, since that file lives there
   directly). Anything outside `apps/api/` -- including all of Alembic's
   config and migration scripts -- is never copied into the deployed image
   at all.

So even manually exec'ing into the running container would not have
worked: the `alembic` tool and the migration script simply don't exist
there. Nothing in this pipeline has ever run a migration against a real
Postgres instance -- QA Lead's testing was against in-memory SQLite only,
which was flagged as an open risk in the original deploy checklist.

## Decision

**1. Relocate Alembic into `apps/api/`.** `alembic.ini` and `alembic/` move
from the repo root into `apps/api/alembic.ini` and `apps/api/alembic/`.
This makes `apps/api/` a fully self-contained deployable unit -- code,
Dockerfile, requirements, and migrations together -- matching the build
context Railway already uses. This is a precondition for any execution
strategy, not just the one below.

**2. Run migrations via Railway's Pre-Deploy Command, not a CI/CD job.**
Railway's `finance-tracker-app` service auto-deploys directly off `git
push` (its own GitHub integration trigger), completely independent of
whether GitHub Actions has run or passed. A migration step added to
`.github/workflows/ci-cd.yml` would race against that independent Railway
trigger, with no guarantee the migration completes before the app
container starts.

Railway's [Pre-Deploy Command](https://docs.railway.com/deployments/pre-deploy-command)
feature exists for exactly this case: it runs in a separate container
between build and deploy, with the same image, dependencies, environment
variables, and private network access as the app itself -- and if it
exits non-zero, the deploy does not proceed and the app is never started
against an unmigrated schema. This is a stronger, better-ordered guarantee
than anything a parallel CI job could offer.

**One-time setup Monty needs to apply himself** (Railway dashboard, not
something available via API): `finance-tracker-app` service → Settings →
Deploy → Pre-Deploy Command:

```
cd apps/api && alembic upgrade head
```

## Verified gotcha — do not "simplify" this command later

`alembic.ini`'s `script_location = alembic` is a path resolved against the
**current working directory at invocation time**, not against the ini
file's own directory. Confirmed empirically in a sandbox simulation of the
exact container layout: running `alembic -c apps/api/alembic.ini upgrade
head --sql` from a working directory of `/app` failed with `Path doesn't
exist: '/app/alembic'`. Running `cd apps/api && alembic upgrade head --sql`
from within `apps/api/` succeeded and produced the correct `CREATE TABLE
users` DDL. The `cd` is load-bearing -- a `-c`/`--config` flag shortcut
from the image's `WORKDIR` (`/app`) will not work.

## Consequences

**Positive:** migrations now run automatically and safely on every deploy,
in the correct order, with a hard stop if they fail. `apps/api/` is now a
complete, self-contained service directory. Every future story that adds a
migration (FINTRACK-14 onward) gets this for free -- no more manual,
easy-to-forget migration steps.

**Negative:** local development and any future CI step that needs to run
`alembic` directly must `cd apps/api` first (or set an equivalent working
directory) -- this is a minor workflow change from the old repo-root
invocation, but is not enforced or checked anywhere automatically, so it's
worth remembering.

**No changes** to `apps/api/Dockerfile` (still uvicorn-only at
`ENTRYPOINT`) or `.github/workflows/ci-cd.yml` -- this fix is scoped
entirely to file relocation plus a Railway dashboard setting.

## Verification

Reproduced and fixed in a sandbox simulation of the container's exact
filesystem layout (same structure used to verify the earlier Dockerfile
fix): copied the real `apps/api/` source tree plus the relocated
`alembic.ini`/`alembic/`, set `PYTHONPATH` to match the container's `/app`,
and ran `alembic upgrade head --sql` (offline mode -- generates DDL without
needing a live database connection, but exercises the exact same
config-resolution and import chain a real run would). Output correctly
showed the `CREATE TABLE users` statement with all expected columns and
the unique index on `email`, confirming the relocated config, `env.py`'s
`apps.api.*` imports, and the migration script itself all resolve
correctly from the new location.
