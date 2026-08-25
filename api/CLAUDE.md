# API Layer — Claude Code Guide

FastAPI 0.115+ (Python 3.12). Two databases: `APP_DATABASE_URL` (read-write) and
`WAREHOUSE_DATABASE_URL` (read-only, `marts` only). Runs on **Azure SQL** or
PostgreSQL — see *Database portability* below, which is the part of this layer
most likely to bite.

## Structure & layering

```
api/app/
├── main.py         entrypoint, lifespan, middleware, router registration
├── config.py       pydantic-settings — every env var typed here
├── database.py     two async engines + session dependencies
├── sql_compat.py   the PostgreSQL / Azure SQL syntax differences, in one place
├── redis.py        Redis client (optional — see below)
├── storage.py      fsspec abstraction (STORAGE_URI)
├── secrets.py      secrets backend resolver (SECRETS_BACKEND)
├── routers/  services/  models/  schemas/
└── middleware/     auth.py (JWT)
```

**router (HTTP) → service (logic) → model (DB)** — never touch SQLAlchemy models
from a router.

## Routers

| File | Prefix | Purpose |
|---|---|---|
| `auth.py` | `/auth` | Tokens, TOTP, OAuth exchange |
| `admin.py` | `/admin` | Users, roles, feature flags, auth config, invites, portal navigation |
| `users.py` | `/users` | Own profile, password, avatar, org directory (**self-service only**) |
| `portal.py` | `/portal` | Effective feature flags and branding for the shell |
| `dashboards.py` | `/dashboards` `/admin/dashboards` | CRUD, shares, filters, versions |
| `embed.py` | `/embed` | Power BI embed tokens, workspace/report discovery |
| `pages.py` | `/pages` `/admin/pages` | Custom HTML pages + versions |
| `bi_connections.py` | `/bi-connections` | BI connection CRUD (Power BI) |
| `data_pipelines.py` | `/data-pipelines` | ADF connection CRUD, sharing, run monitoring |
| `pipeline_notifications.py` | `/data-pipelines/{id}/…` | Alert config, conditions, delivery history |
| `notifications.py` | `/notifications` | Per-user preference CRUD |
| `warehouses.py` | `/warehouses` | Warehouse connection CRUD + query-access grants |
| `data_dict.py` | `/data-dictionary` | Entries, tree, relationships, exclusions, per-connection shares |
| `data.py` | `/data` | Paginated mart queries + freshness |
| `exports.py` | `/exports` | SQL reports and the run log (searchable); execution is the worker's |
| `changes.py` | `/changes` | Change-ledger history and revert |
| `audit.py` | `/audit` | Audit log, retention policy, purge |
| `favorites.py` | `/favorites` | Per-user bookmarks |
| `search.py` | `/search` | Cross-resource search (dashboards + pages) |

Services mirror routers in `services/`. Notable: `crypto.py` (Fernet, bcrypt,
TOTP), `permissions.py` (permission keys + role ids), `principal_cleanup.py`
(grant cleanup that replaced the user/role cascades), `data_query.py` (org-scoped
mart queries), `change_ledger.py` (snapshot + revert), `embedders/powerbi.py`,
`notifications/dispatcher.py`, `pipeline_poller.py`, `export_runner.py` (the
second periodic runner), `export_source.py` + `sql_guard.py` (read-only report
queries), `cron.py`.

**Adding a router:** create `routers/x.py` → import + `app.include_router(...)`
in `main.py` → `services/x.py` for logic → models if new tables →
`alembic revision --autogenerate -m "..."`.

## Database portability — read this before touching a model

The app runs on Azure SQL **and** PostgreSQL, and the two disagree in three ways
that a mocked test session cannot see.

- **Every `String` column needs an explicit length.** SQLAlchemy's mssql dialect
  raises `CompileError` on a bare `VARCHAR` before the statement reaches a
  server. Lengths follow meaning: 128 for a SQL identifier, 45 for an IP address,
  32 for an enumerated value, 1024 for a URL, 255 as the default.
- **Each table gets exactly one `ON DELETE CASCADE` parent.** SQL Server rejects
  a second cascade route between the same two tables (error 1785); the grant
  tables had three or four routes down from `orgs`. The cascade was narrowed to
  the *owning* parent **on both engines** — a schema that differs per dialect
  means dev and production delete different rows. `services/principal_cleanup.py`
  replaced the rest, and **every path that deletes a user or a role must call it
  first**, or the delete fails on a foreign key. That loud failure is the
  intended mode: a silently orphaned grant hands access to whoever is assigned
  the recycled id.
- **`sql_compat.py` holds the raw-SQL differences** — `paginate_clause`,
  `row_limit_clause`, `schema_freshness_sql`. Anything else PostgreSQL-only
  (`RETURNING`, `ON CONFLICT`, `NOW()`, `pg_*` catalogs) belongs there or nowhere.
  `row_limit_clause` interpolates its limit, so callers pass an int they
  produced — never a request value.
- **`change_ledger.before`/`after` use `JSON().with_variant(JSONB, "postgresql")`.**
  Azure SQL has no binary JSON type; nothing queries *into* the snapshot, so the
  two behave identically here.
- `tests/test_schema_portability.py` pins the first two. CI additionally runs the
  real migration against a real SQL Server, twice.

## Migrations

`alembic/versions/001_initial.py` is the whole schema plus the seed (default org, five system roles, the permission vocabulary and its
role matrix, the admin user, feature flags). It is a fresh fork with no deployed
database to upgrade, so a chain of sixty increments would describe history that
never happened here. Later changes get their own revision as usual —
`002_export_runs.py` is the first.

**Dropping a column with a `server_default` on SQL Server needs the default
constraint dropped first.** It is a separately-named object, and `DROP COLUMN`
fails while it exists. `002_export_runs.py::_drop_default_constraint` is the
helper; PostgreSQL needs none of it. Prove a downgrade works by running
`alembic downgrade` and `upgrade` back — a downgrade nobody has executed is a
downgrade that does not work.

The seed uses SQLAlchemy Core with explicit SELECT-then-INSERT rather than raw
SQL — `RETURNING`, `ON CONFLICT`, and `NOW()` are PostgreSQL spellings, and the
read-before-write is also what makes the whole function idempotent.

## Providers

`services/bi_providers/` and `services/pipeline_providers/` each adapt one
platform to a common interface and expose `ProviderMeta.fields`, which the admin
UI renders the connection form from — so shipping a provider needs no frontend
change. This build registers **Power BI** and **Azure Data Factory** only.

`services/bi_credentials.py` hands the embedder `conn.config` verbatim, so a
`ProviderField.key` the embedder does not read is a silently dead field. A
provider's `test_connection` must exercise the credentials, not just reachability.

## Change ledger and revert

`models/change_ledger.py` + `services/change_ledger.py` record every create,
update, and delete of a tracked resource with a full before/after snapshot.
`log_create`/`log_update`/`log_delete` add a row; the caller commits; failures
are swallowed, because losing the history row must never lose the mutation.

- **`routers/changes.py`** — `GET /changes/{type}/{id}` (resource view-gated),
  `GET /changes` (global feed, `changes.view`), `GET /changes/resource-types`
  (the filter menu, served from the registry), `POST /changes/{id}/revert` and
  `POST /changes/correlation/{cid}/revert` (revert == edit).
- **`services/mutation_registry.py`** maps each resource type to its model, name,
  label, guards, parent FKs, and an optional `pre_delete`. The guards *reuse the
  routers' own* `_require_*` helpers, so there is no second authorization path.
  `top_level_resources()` is what the filter menu reads; it drops anything with
  `parent_fks`, since a child is registered so its parent reverts complete, not
  so a person can filter by it.
- **`org_settings` is registered for the navigation alone**, with `remap_ids`
  wired to `nav_config.remap_nav_ids`. Deleting a dashboard prunes its nav link
  under the delete's correlation id; reverting restores the link, and the remap
  repoints it at the id the recreated dashboard actually got.
- **`pre_delete` exists for children with a NO ACTION foreign key.** Undoing a
  create deletes the row, and a report's runs point back at it, so the delete
  fails on the constraint until they are detached. Registered on `report`;
  needed by any resource whose children are not cascade-deleted.
- **A delete that cascades snapshots its children** under one `correlation_id`,
  parent first, so the group revert recreates the parent before remapping the
  children's FK onto its new primary key. `routers/dashboards.py` is the worked
  example.
- **Reverting an update ignores `created_at`/`updated_at`** —
  `_SERVER_MANAGED_COLUMNS` is excluded from the optimistic-concurrency check
  because `onupdate=func.now()` evaluates during flush, after the snapshot was
  taken. Folding them back in 409s every revert.
- Tracked so far: dashboards (+ filters, shares), custom pages, data dictionary
  entries, SQL reports, the portal navigation.

## Portal navigation

`GET`/`PUT /admin/nav-config` (admin) and the `nav_config` field of
`GET /portal/settings` (any authenticated user, because the nav is rendered for
everyone).

- **`schemas/nav_config.py` is an href allow-list**, not a shape check that
  happens to include one. An internal path starting with `/`, or an absolute
  `http(s)` URL — nothing else. The stored value is rendered into an anchor for
  every user in the org, so `javascript:`, `data:`, and the protocol-relative
  `//host` (which reads local and resolves off-site) are all refused.
- **A link needs an href and a dropdown needs children**, checked as a model
  validator. Either half-finished shape renders as a nav that looks broken.
- **`services/nav_config.py` prunes links to deleted resources** and is called
  from the dashboard, warehouse-connection, and pipeline-connection delete
  handlers. It swallows every error: a stale nav entry is cosmetic, a failed
  delete is not.
- **Saving `{"items": []}` stores SQL NULL**, so the default has one
  representation. The column is `JSON(none_as_null=True)` — plain `JSON` writes
  Python `None` as the JSON string `'null'`.

## Database sessions

`get_app_db` (writes OK) and `get_warehouse_db` (read-only, marts) from
`app.database`. Never write via `get_warehouse_db`; never run data queries via
`get_app_db`.

## Authentication

All routes except `/auth/*` and `/health` require `Authorization: Bearer <JWT>`.
`middleware/auth.py` resolves it into a `CurrentUser` (`user_id`, `org_id`,
`role`, `email`).

`require_role()` returns a FastAPI **dependency, not a decorator** — pre-bind at
module level:

```python
_admin_dep = require_role("admin", "superadmin")

@router.get("/admin/users")
async def list_users(current_user: CurrentUser = Depends(_admin_dep), ...): ...
```

`ROLE_HIERARCHY` (`viewer=0, analyst=1, manager=2, admin=3, superadmin=4`) is a
min-level check, so `require_role("admin")` also passes superadmins.

## Access control & sharing model

**Permissions, not role levels, drive feature access.** `ROLE_HIERARCHY` backs
`require_role` for coarse admin gates only; resource access is decided by
permission keys attached to a user's roles. Use `require_permission(...)` or
`require_permission_or_admin(...)` from `services/permissions.py`.

**Two-layer model — broad permission OR per-resource grant:**

| Grant table | Resource | Unlocks feature |
|---|---|---|
| `DashboardPermission` | dashboard | `dashboards` |
| `CustomPagePermission` | custom page | `custom_pages` |
| `DataDictionaryPermission` | data dictionary (per connection) | `governance` |
| `WarehouseConnectionPermission` | warehouse (query access) | — |
| `DataPipelineConnectionPermission` | pipeline connection | `pipelines` |

Rules that must hold (regressions here leak data):

- **`view` vs `edit` is a role permission, never a per-resource grant.** The
  `can_edit` column is dead — editing is the `*.manage` permission.
- **Feature visibility is grant-aware.** `_grant_unlocked_features` in
  `routers/portal.py` turns a feature on when the org flag is enabled AND (the
  user holds a mapped permission OR a resource of that type is shared with their
  roles). One `UNION ALL`, because this runs on every page load.
- **Admins/superadmins bypass the gate** — the role check runs first, so no
  permission or grant query runs for them.
- **One shared role-id query:** every grant check uses `get_user_role_ids` from
  `services/permissions.py`. Never reimplement it inline; divergence is a
  security risk.
- **Sharing endpoints are org-scoped and 404 on missing or cross-org resources**
  before writing grants.
- **There are no `admin.*` permission keys** — each would let its holder become a
  full admin, so it is an escalation path rather than a delegation.

## Notifications

- **Generic dispatcher** — `dispatch_event(...)` from
  `services/notifications/dispatcher.py`: reads `NotificationPreference`,
  rate-limits through Redis when available, pushes to Redis streams.
- **Delivery history** — every `send_to_groups` call records a
  `NotificationDelivery` row with the per-destination outcome. Webhook URLs and
  phone numbers are **redacted** before storage: an incoming webhook URL *is* the
  credential. The row is flushed, never committed — the caller owns the
  transaction — and a failed audit write is swallowed, because losing the history
  row must never lose the notification. Pruned after 30 days by the poller tick.
- **Alert suppression** (`services/alert_suppression.py`) — pure, DB-free,
  unit-tested. Two invariants: **failures pass quiet hours** unless
  `quiet_hours_include_failures`, and **quiet hours are checked before the
  throttle** — a held alert must not consume the throttle window, or the first
  alert after quiet hours end is itself throttled away. `start == end` and an
  unknown timezone both mean "no suppression", never "silence everything".
- **Pipeline monitoring** — `services/pipeline_poller.py` is the API's only
  periodic runner (asyncio loop in the lifespan, 60s tick, Redis lock across
  workers). It diffs runs per `PipelineNotificationConfig` and evaluates
  `NotificationCondition` checks (`pipeline_idle`, `data_freshness`). Condition
  alerts are state-transition based — trip, then optionally recover, never
  re-alert while still triggered; a probe error is recorded without flipping the
  state.
- **Redis is optional.** Both the poller lock and the rate limiter catch and
  continue when it is unreachable. That is what makes a single-node deployment
  Redis-free — but it also means **more than one API replica needs Redis**, or
  each one polls and the same alert goes out several times.

## Data dictionary

`routers/data_dict.py` + `services/warehouse_inspector.py`. Entries are
per-`(org, connection, schema, table, column)`; a NULL `column_name` describes
the table itself. Field-level edits append to `data_dictionary_changelog`, which
is never updated or deleted.

- **Dictionary access and warehouse query access are separate grants.**
  `DataDictionaryPermission` controls who reads the dictionary for a connection;
  `WarehouseConnectionPermission` controls who can query it. Never collapse them.
- Population reads live schema through `warehouse_inspector`, so a dropped column
  disappears from the tree without a manual edit.

## Performance

Listing endpoints must be **constant** in the number of rows returned. The shape
to watch for is a DB `await` inside a `for` loop. Measure before changing
anything — attach a `before_cursor_execute` listener to `app_engine` and compare
counts at two data sizes. Not every loop is an N+1: slug-collision `while` loops
are bounded by collisions, and batched `in_(...)` lookups are already one query.

| Endpoint | Now |
|---|---|
| `_grant_unlocked_features` (every page load) | 1 `UNION ALL` |
| `get_roles` / `create_role` / `update_role` | 1 grouped query each |
| `GET /admin/overview` | 6 queries, whatever the org size |

## Run & test

```bash
cd api && pip install -e ".[dev]"
alembic upgrade head
uvicorn app.main:app --reload --port 8000       # Swagger: /docs
python -m pytest tests/ -q                      # unit tests — mocked DB
python -m pytest tests/ -m integration          # needs TEST_DATABASE_URL
ruff check app/ tests/ alembic/                 # tests must lint clean too
```

### Test pattern (copy this)

Layout: `tests/routers/test_<router>.py`, `tests/services/test_<service>.py`,
shared fixtures in `conftest.py`. Name
`test_<thing>_<condition>_<expected_outcome>`, group in `Test<Subject>` classes,
Arrange/Act/Assert.

Call endpoint and service functions **directly** with fixtures — no HTTP client,
no `Depends()`; pass `current_user=` explicitly. Fixtures: `mock_admin_user`,
`mock_superadmin_user`, `mock_db_session` (an `AsyncMock`; set `.execute` per
test), and the autouse `grant_governance_permissions`.

Shape `db.execute` results: `.scalar_one_or_none()` for existence,
`.scalars().all()` for ORM lists, `.all()` for tuple rows, `.first()` for
`limit(1)`. Multiple queries → `AsyncMock(side_effect=[r1, r2, ...])` in call
order. Patch collaborators **where they're imported**, not where defined.

**Every access-control change tests:** admin bypass, permission-holder allowed,
grant-holder allowed without permission, neither denied, org flag disabled
overrides both, 404 on missing or cross-org resource. Templates:
`test_portal.py`, `test_warehouses.py`, `TestGetDictPermissions` /
`TestSetDictPermissions` in `test_data_dict.py`.

## Read first

`app/config.py`, `app/database.py`, `app/sql_compat.py`, `app/middleware/auth.py`,
`app/services/permissions.py`, `alembic/versions/001_initial.py`
