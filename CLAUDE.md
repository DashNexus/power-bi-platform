# Power BI Platform — Claude Code Guide

A pared-down fork of the full BI platform: publishes Power BI reports and page
embeds to an organisation, plus the governance surface around them (data
dictionary, connections, ADF pipeline monitoring, audit, change history, users
and roles). Runs on **Azure SQL** or PostgreSQL; deploys to Azure Container Apps.

## Layers

| Directory | Stack | Purpose |
|---|---|---|
| `api/` | FastAPI, Python 3.12 | Every endpoint, the schema, all access control |
| `application/` | Next.js 15 + TypeScript | Portal, dashboards, admin console |
| `deploy/` | Bicep + bash + GitHub Actions | Azure infrastructure and CI/CD |

**Each layer has its own CLAUDE.md** — consult it when working in that layer.

## Two databases

- **`APP_DATABASE_URL`** — users, roles, dashboards, pages, connections,
  notifications, exports, audit log, change ledger. Locally this is
  `bi_platform_database` on a SQL Server at `localhost:1433`.
- **`WAREHOUSE_DATABASE_URL`** — read-only to the API, `marts` schema only; what
  the data dictionary describes and exports read from. It may share the
  application database (it does locally) or name a separate one.

`scripts/dev.sh` uses whichever server `APP_DATABASE_URL` names and only starts
the compose container when that server is unreachable.

## Run locally

```bash
./scripts/dev.sh          # everything: .env, deps, database, migrations, both servers
./scripts/dev.sh --check  # preflight only, changes nothing
```

Sign in as `admin@example.com` / `admin123`. `make help` lists the individual
targets if you want to run a step on its own; note `make` is not installed on
every dev box, and the script does not need it.

## Scope — what this build deliberately does not have

Checking this list first saves rediscovering a deletion as a bug. Removed from
the parent platform, with the routers, models, components, and permission keys
gone rather than disabled: **AI chat and the assist panel**, ERDs, data lineage,
timelines, manual datasets, tickets, project planning, time tracking, billing,
backups, retention policies, Streamlit, API keys, and the **organisation-settings
console**.

Narrowed rather than removed:

- **Embeds are `powerbi` or `page`.** `EmbedType` is a `Literal` in
  `api/app/schemas/dashboard.py` and a union in `application/src/types/embed.ts`;
  both must change together. A `page` embed is an ordinary URL in an iframe with
  no BI connection behind it.
- **The only BI provider is Power BI**, the only pipeline provider is **Azure
  Data Factory**, and the only identity provider is **Microsoft Entra ID**. Each
  registry still renders its admin form from provider metadata, so adding one
  back is a module plus a registry entry — not a frontend change.
- **Feature flags have no admin page.** `/admin/features` was removed; the API
  (`GET`/`PUT /admin/features/{key}`) and `FEATURE_*` env overrides are what is
  left, so a flag changes through Swagger or the database. `GET /portal/features`
  still drives every gate in the frontend.
- **Notification channels have no org-level console.** `/admin/notifications` was
  removed. Per-connection delivery is configured on `/pipelines/[id]` →
  Notifications, recipients on `/admin/notification-groups`, and a user's own
  preferences on `/settings/notifications`.
- **Power BI credentials belong to a BI connection, not to the org.**
  `/admin/bi-connections` holds as many as needed; the single org-wide service
  principal card on `/admin/auth-config` is gone, because it could only ever
  describe one of them. `_load_powerbi_config` still falls back to a legacy
  org-global `powerbi_sp` row when a dashboard has no `bi_connection_id` — the
  dashboard editor requires one, so that path is only reachable by rows created
  before connections existed.
- **`org_settings` survives with five columns** (`app_name`, `logo_url`,
  `audit_retention_days`, `nav_config`, `updated_at`). There is still no
  org-settings console: each field is edited from the page that owns it — audit
  retention from the audit page, the navigation from `/admin/nav-config` —
  because each is a property of a thing rather than a general preference.

## Architecture rules (do not break these)

Every one is here because it was violated, or would be by the obvious change.

### Database portability — the app runs on Azure SQL *and* PostgreSQL

- **Every `String` column has an explicit length.** SQLAlchemy's mssql dialect
  raises `CompileError` on a bare `VARCHAR` before the statement reaches the
  server, and a unique constraint needs a bounded column anyway. Lengths follow
  the column's meaning — 128 for a SQL identifier, 45 for an IP, 1024 for a URL.
- **Each table has exactly one `ON DELETE CASCADE` parent.** SQL Server rejects
  a second cascade route between the same two tables (error 1785) where
  PostgreSQL allows it; the grant tables had three or four routes down from
  `orgs`. The cascade was narrowed to the *owning* parent **on both engines**
  rather than diverging per dialect — dev and production deleting different rows
  is exactly the bug that surfaces late. `services/principal_cleanup.py` is what
  replaced the rest, and **every path that deletes a user or a role must call
  it first**.
- **Raw SQL differences live in `api/app/sql_compat.py`** — row limiting, the
  schema-freshness probe, and the boolean predicates. `RETURNING`, `ON CONFLICT`,
  `NOW()`, `LIMIT`/`OFFSET`, and `pg_*` catalogs are PostgreSQL spellings.
- **Never write `column.is_(True)`.** SQLAlchemy renders it as `col IS 1` on SQL
  Server and T-SQL's `IS` accepts only NULL, so the statement fails to parse. Use
  `is_true()` / `is_false()` from `sql_compat`. (`is_(None)` is fine either way.)
- **Every paginated query needs an `ORDER BY`.** SQL Server rejects `OFFSET`
  without one, and PostgreSQL silently makes page 2 unrelated to page 1.
- **`alembic/env.py` maps each async driver to a sync one** (`_SYNC_DRIVERS`).
  Migrations run synchronously; handing a sync engine an async DBAPI fails
  mid-migration with `MissingGreenlet`, which reads like an application bug.
- **Both rules are pinned by `api/tests/test_schema_portability.py`**, and CI
  runs the real migration against a real SQL Server twice (the second run proves
  the seed is idempotent). A mocked session cannot catch either.

### Exports and reports

- **A report's SQL is read-only by four layers, and only the last is airtight.**
  (1) `services/sql_guard.py` refuses anything that is not a single SELECT,
  checked at write time *and* again by the worker before execution. (2) On
  PostgreSQL the transaction is `SET TRANSACTION READ ONLY`, so the server
  refuses writes instead of us predicting them; SQL Server has no equivalent.
  (3) The transaction is always rolled back. (4) The connection should use a
  SELECT-only login — a database that refuses the write beats any parsing.
- **The rollback does not cover everything, which is why the keyword list is
  long.** Sequence advances (`nextval`, `setval`, `NEXT VALUE FOR`) are
  non-transactional on both engines, `dblink` writes to another server, and
  `lo_export` writes a file on the host. A rollback undoes none of them, so for
  these the parser is the *only* layer. Do not prune the list on the grounds
  that "the rollback catches it".
- **`tests/services/test_sql_guard.py` holds an adversarial suite** — every
  known way to write from a statement that leads with SELECT or WITH, plus a
  matching list of ordinary queries that must not be false positives. A guard
  that rejects real queries gets switched off, so both halves matter. Add to it
  rather than replacing it.
- **A report against the operations database is admin-only.** That database
  holds every organisation's rows, so the query is not org-scoped the way
  `/data` is. Tables holding credentials are refused outright
  (`_OPERATIONS_DENYLIST`). Warehouse-source reports instead require query
  access to the chosen connection (`user_can_query_connection`).
- **Nothing executes in a request handler.** `POST /exports/reports/{id}/run`
  queues a job with status `pending` and returns; `services/export_runner.py`
  runs it on a 30-second tick. Creating a job as `running` is what left every
  job stuck at that status before the worker existed — never do it again.
- **`export_jobs` is the run log.** One row per execution, scheduled or manual,
  with `started_at`, `row_count`, `file_size_bytes` and the error. Rows and
  their files are purged after `RESULT_RETENTION_DAYS` (30).
- **The run log is searched server-side.** Both `GET /exports/jobs` and
  `GET /exports/reports/{id}/runs` take `search`, `status` and `trigger_type`,
  because the log is capped by a limit: filtering in the browser would answer
  "no matches" for a run sitting just past it. `search` covers the name, format
  and error, and `_escape_like` escapes `%` and `_` — without it, searching for
  a report named "100% sample" returns every row.
- **The status filter offers no "cancelled".** `cancel_job` marks a cancelled
  run `failed` with "Cancelled." as its message, so the option could only ever
  return nothing. An unrecognised status is a 400 rather than an empty list — a
  filter that answers "no results" to a typo looks exactly like one answering it
  to a real query.
- **A run stuck in `running` past `STUCK_JOB_TIMEOUT` is failed by the reaper.**
  A killed worker must not be able to strand a report for ever, and a stuck run
  also blocks the next one (the 409 on a duplicate Run now).
- **Cron parsing is `services/cron.py`, not a dependency.** Five fields, with
  the standard day-of-month/day-of-week union. `is_due` catches up a slot the
  worker was down for, capped at a day so a long outage does not fire a burst.
- **`export_jobs.trigger_type` is not called `trigger`** — that is a reserved
  word in T-SQL, and every hand-written query against the table fails on it.
- **What a report may cost is bounded on four axes**, all in `config.py`:
  a server-side statement timeout (`_apply_statement_timeout` — cancelling on
  our side leaves the warehouse still working), a row cap, a *cell* cap (a
  thousand rows of three hundred columns costs what a hundred thousand of three
  does, and only one of them looks large), and one job at a time per report.
- **`POST /exports/reports/test` runs a definition without saving it** — fewer
  rows, a shorter timeout, no job row, no file, no delivery. It applies the same
  access checks as saving, or Test would be a way to read a connection you may
  not report on.
- **Driver errors are scrubbed by value, not by suspicion.** The message names
  the column that does not exist, which is the whole point of Test;
  `_safe_driver_message` removes the known URL and password rather than
  discarding anything containing `://` — SQLAlchemy appends a docs link to every
  error, so the suspicious version redacted all of them.
- **Email delivery is refused by the API, not just hidden in the UI**
  (`_UNAVAILABLE_DELIVERY_METHODS`). A report saved with a delivery that never
  runs is worse than one that refuses to save.

### Portal navigation

- **The navigation an admin authors is stored validated, never verbatim.**
  `schemas/nav_config.py` is an allow-list of two href shapes — an internal path
  starting with `/`, or an absolute `http(s)` URL. Everything else is refused,
  because the saved value is rendered into an anchor for every user in the org
  and `javascript:` would be stored XSS an admin could hand to themselves by
  pasting a link. `//evil.example.com` is refused too: it reads as a local path
  and resolves off-site.
- **Configuring a link does not grant access to its destination.** PortalNav
  filters every item through `lib/navAccess.ts`, against the same feature flags
  and grants the routes enforce — so an admin can put any dashboard in the nav
  and only people who could already open it will see it. That is a display rule;
  the route is still the thing that says no.
- **A nav link must not outlive the resource it points at.** Nothing ties an
  href to a live row, so `services/nav_config.py` prunes entries when a
  dashboard, warehouse connection, or pipeline connection is deleted, and drops
  a dropdown the prune emptied. It never raises: a stale nav entry is cosmetic,
  and failing someone's delete over the cleanup is not. Custom pages are
  deliberately *not* pruned — they are soft-deleted, and the access check
  already hides an unpublished page's link.
- **The prune joins the delete's `correlation_id`**, so reverting the delete
  restores the nav entry with the resource. `remap_ids` on the registry entry
  then repoints the restored href, because recreating a deleted row assigns it a
  fresh primary key and the snapshot names the old one.
- **Saving an empty navigation stores SQL NULL**, so "use the defaults" has one
  representation rather than two. `JSON(none_as_null=True)` on the column is
  what makes that true — plain `JSON` stores Python `None` as the JSON *string*
  `'null'`, which reads back as `None` but never matches `IS NULL`.

### Access control

- **Access is permission- and grant-driven, not role-level.** Permission keys
  (`services/permissions.py`) plus per-resource grants; `ROLE_HIERARCHY` gates
  only coarse admin surfaces.
- **`view`/`edit` is a role permission, never a per-resource grant.** Grants are
  role-only and view-only; editing is the `*.manage` permission. The `can_edit`
  columns on grant tables are dead — do not revive them.
- **Feature visibility is grant-aware.** `GET /portal/features` turns a feature
  on when the org flag is enabled AND (the user holds a mapped permission OR a
  resource of that type is shared with their roles). An org-disabled feature
  stays off regardless of grants. One `UNION ALL`, not one query per type — this
  call sits in the shell on every page load.
- **There are no `admin.*` permission keys.** Each would let its holder become a
  full admin (assign roles, edit role permissions, register an identity
  provider), so they are an escalation path, not a delegation.
  `require_role("admin")` gates those surfaces.
- **Access-control changes ship with tests**: admin bypass, permission-allowed,
  grant-allowed-without-permission, denied, org-flag-disabled, 404 cross-org.

### Data boundaries

- **All `/data/*` queries append `WHERE org_id = :org_id`** — enforced in
  `services/data_query.py`; never bypass.
- **The warehouse session is read-only and `marts`-only.** Never write through
  `get_warehouse_db`; never run mart queries through `get_app_db`.
- **`row_limit_clause` interpolates its limit**, so callers pass an int they
  produced — never a request value that reached them as a string.

### Secrets and abstractions

- **No cloud SDK imports outside `api/app/storage.py` and `api/app/secrets.py`.**
- **TOTP secrets and provider client secrets are Fernet-encrypted** via
  `services/crypto.py`; never store plaintext.
- **Middleware uses `authConfig`, not `auth`** — `authConfig` has no providers
  and makes no network calls, which is what makes it Edge-safe.
- **`NEXTAUTH_SECRET` is shared between both layers.** The API verifies the JWT
  Auth.js signed; a mismatch shows up as "login works, every call 401s".

### Resource lifecycle

- **Ledger-tracked mutations call `services/change_ledger.py` before commit** so
  the change appears in `/changes` and can be reverted. Wired: dashboards (with
  their filters and shares under one `correlation_id`), custom pages, data
  dictionary entries, SQL reports. Adding a resource means registering it in
  `services/mutation_registry.py` *and* adding the `log_*` calls — a resource
  with only one half is silently absent from the feed, which is how reports
  went unrecorded while their audit entries were being written normally.
- **The `log_*` call goes after the flush, not after `db.add`.** The snapshot is
  taken from the object it is handed, and before the flush that object has no
  primary key — so the entry records `resource_id=None` and nothing can tie it
  to the row, or revert it.
- **A resource whose children hold a NO ACTION foreign key needs `pre_delete`.**
  Undoing a *create* means deleting the row, and every run of a report points
  back at it, so the delete fails on the constraint until the runs are detached.
  The descriptor's `pre_delete` hook does that — it is the same work the
  resource's own delete handler already does.
- **A registered resource inherits its router's visibility rule, not a looser
  one.** Reports are scoped to their author with no admin bypass
  (`_load_report`), so the registry's guards are too: an admin sees *that* a
  report changed in the feed and reverts only their own. A guard laxer than the
  router turns `/changes` into a way around it.
- **A delete that cascades must snapshot its children.** Deleting a dashboard
  takes its filters and shares with it; reverting only the parent restores a
  dashboard with no filters that nobody it was shared with can see.
- **Reverting an update ignores `created_at`/`updated_at`.**
  `_SERVER_MANAGED_COLUMNS` is excluded from the optimistic-concurrency check
  because `onupdate=func.now()` evaluates during flush, *after* `log_update`
  snapshotted the row. Folding them back in makes every revert 409.

### Deployment

- **`NEXT_PUBLIC_API_URL` is inlined into the browser bundle at build time**, so
  infrastructure is provisioned *before* the frontend image is built, and a
  frontend image cannot be promoted between environments.
- **The API's `maxReplicas` is 1 unless Redis is deployed.** The pipeline poller
  runs on a timer in-process; without the Redis lock every replica runs the same
  tick and the same alert goes out several times.
- **Redis is optional.** Both call sites (`pipeline_poller.py`,
  `notifications/dispatcher.py`) degrade gracefully when it is unreachable.

## Testing

```bash
make test          # both layers
make test-api      # API unit tests — mocked DB, nothing to start
make test-app      # frontend unit tests
make lint          # ruff + mypy + eslint
make typecheck     # tsc --noEmit
```

**Unit tests are necessary, not sufficient.** The failures that reach a
deployment here are server-side and invisible to a mocked session — see
*Database portability* above for the two that are now pinned by a real-database
CI job.

**The two layers only meet in `tests/test_frontend_api_paths.py`.** It resolves
every API path literal in `application/src` against the mounted routes. `tsc`
cannot know what the API serves and the API's tests never see the client, so a
page calling a path that does not exist is invisible to both — which is how
`/admin/audit` came to request `/governance/audit` and report it as "Failed to
load audit log." for as long as it did.

## Known state — read before "fixing" these

| Thing | State |
|---|---|
| `ruff check app/` reports ~60 findings | **Pre-existing baseline** inherited from the parent repo, mostly `D417` and long lines in untouched files. Lint only the files you touch. |
| `application/.next` | `next build` runs clean; a dev server holding a lock on `.next/trace` will fail it — `NEXT_DIST_DIR` targets a scratch directory in that case. |
| Seeded `admin@example.com` / `admin123` | Created by the migration so the first sign-in works at all. Change it immediately; the README and deploy docs both say so. |
| SQL firewall rule `0.0.0.0` | Deliberate in the template — it is how Container Apps reaches SQL without a fixed egress IP. Replace with VNet integration before production (`deploy/README.md` → *Hardening*). |
| `/admin/features` and `/admin/notifications` return 404 | **Removed pages**, not a routing fault. Nothing links to them; `AdminOverview.test.tsx` asserts they stay unlinked. |
| Export results vanish after 30 days | **Deliberate** — `export_runner.RESULT_RETENTION_DAYS`. The worker deletes the file and the run row; downloading an expired run returns 410, not 404, so the client can tell it apart from one that never existed. |
| A `server_default` column cannot be dropped on SQL Server | It creates a separately-named DEFAULT constraint that blocks `DROP COLUMN`. Migration 002 has `_drop_default_constraint` for this; copy it into any migration whose downgrade drops such a column. |
| There is no Schedules tab, and no `POST /exports/jobs` | **Both removed** (migration 003). Schedules recorded when and where to deliver but never *what*, so nothing could run one. `POST /jobs` queued arbitrary SQL without `_validate_report_source`, letting a non-admin read the operations database. A report plus a run replaces both, with one set of guards. `tests/routers/test_exports.py::TestRemovedEndpoints` asserts they stay gone. |
| The change feed's type filter is fetched, not hard-coded | `GET /changes/resource-types` serves it from the mutation registry. The list used to be written out in `admin/changes/page.tsx`, where it had drifted to offer projects, tasks, tickets and ERDs — none of which exist here — while omitting every type that does. Do not re-inline it. |
| Three frontend call sites point at routes that do not exist | `/pipelines/adf/test` (the ADF "Test connection" button on `/admin/auth-config`) and two `/embed/tableau/*` calls in `DashboardCreator`. Each needs a product decision, not a renamed string: ADF connections moved to `/admin/data-pipelines` and are tested per-connection, and Tableau is not a provider in this build. They are named in `tests/test_frontend_api_paths.py::_KNOWN_DEAD_PATHS`, which fails if a fourth appears — or if one of these is fixed and the entry left behind. |
| Entra SSO ships unconfigured | The wiring is complete; the three `AZURE_AD_*` variables are blank, so password sign-in is the only route until a tenant is registered. This is the intended placeholder state. |
| Local DB is published on port 15433 | Not 1433 — a dev box with SQL Server installed already owns that, and can hold several ports at once. `scripts/dev.sh` detects a foreign listener and names the process. |
| Azure SQL Edge reads `SA_PASSWORD`, not `MSSQL_SA_PASSWORD` | Given only the newer name it starts, reports healthy, and leaves `sa` unusable. Setting **both** fails the same way. `docker-compose.yml` sets the older name alone — do not "modernise" it. |

## Style & commit conventions

@STYLE.md

@SKILL.md

Load on demand: `@REVIEW.md` (PR reviews).
