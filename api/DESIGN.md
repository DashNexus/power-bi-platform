# BI Platform API Layer — Design Document

FastAPI backend providing authentication, data access, AI chat, embed token generation, pipeline management, governance, and notifications for the BI Platform.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Router Inventory](#2-router-inventory)
3. [Service Layer](#3-service-layer)
4. [Database Schema](#4-database-schema)
5. [Authentication Architecture](#5-authentication-architecture)
6. [AI Chat Architecture](#6-ai-chat-architecture)
7. [Embed Architecture](#7-embed-architecture)
8. [Notification System](#8-notification-system)
9. [Feature Flag System](#9-feature-flag-system)
10. [Implementation Status](#10-implementation-status)
11. [Testing Plan](#11-testing-plan)
12. [Additional Features](#12-additional-features)

---

## 1. Architecture Overview

### 1.1 Tech stack

| Component | Technology | Version |
|---|---|---|
| Framework | FastAPI | 0.115+ |
| Runtime | Python | 3.12 |
| ORM | SQLAlchemy (async) | 2.0 |
| Migrations | Alembic | 1.13+ |
| AI | LlamaIndex + Anthropic Claude | 0.10+ / claude-sonnet-4-6 |
| Cache | Redis (aioredis) | 5.x |
| HTTP client | httpx (async) | 0.27+ |
| Encryption | cryptography (Fernet) | 42.x |
| Validation | pydantic-settings | 2.x |

### 1.2 Request lifecycle

```
HTTP request
    │
    ▼  CORS middleware
    │
    ▼  JWT validation (middleware/auth.py)
    │   → extracts user_id, org_id, role → request.state.user
    │   → skips /auth/*, /health, /hooks/*
    │
    ▼  Router handler
    │   → require_role("admin") Depends() if needed
    │   → get_app_db() or get_warehouse_db() Depends()
    │
    ▼  Service call
    │
    ▼  SQLAlchemy async query
    │
    ▼  Pydantic response schema
    │
HTTP response
```

### 1.3 Database dependencies

Two session factories in `app/database.py`:

```python
# For write operations against application tables
async def get_app_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(app_engine)() as session:
        yield session

# For read-only access to marts schema
async def get_warehouse_db() -> AsyncGenerator[AsyncSession, None]:
    async with async_sessionmaker(warehouse_engine)() as session:
        yield session
```

The `warehouse_engine` connects as the `warehouse_reader` PostgreSQL role — `SELECT` on `marts.*` only, no DML.

### 1.4 Architecture rules (must not be broken)

1. No cloud SDK imports outside `storage.py` and `secrets.py`
2. All `/data/*` routes use `data_query.py` which enforces `WHERE org_id = :org_id`
3. AI chat is read-only against `marts` schema only
4. Spark writes to object storage only — never direct DB writes
5. TOTP and OAuth secrets always Fernet-encrypted; never plaintext in DB
6. Retention DELETEs require dry-run first (`auto_apply=False` default must not be changed)
7. Schema drift ALTER TABLE uses PostgreSQL advisory locks
8. `require_role()` returns a FastAPI `Depends()` — never used as a decorator

---

## 2. Router Inventory

All 15 routers are registered in `app/main.py`.

### 2.1 `auth` — `/auth`

| Method | Path | Description | Auth required |
|---|---|---|---|
| POST | `/auth/token` | Credential login; returns JWT + user metadata | No |
| POST | `/auth/refresh` | Refresh access token | Bearer token |
| GET | `/auth/me` | Current user profile | Bearer token |
| POST | `/auth/oauth-exchange` | Exchange OAuth provider token for platform JWT | No |

**Status:** ✅ Complete

### 2.2 `admin` — `/admin`

| Method | Path | Description | Role |
|---|---|---|---|
| GET / POST | `/admin/users` | List users / invite | admin |
| GET / PUT / DELETE | `/admin/users/{id}` | Get / update / deactivate | admin |
| GET / POST | `/admin/roles` | List / create roles | admin |
| GET / PUT / DELETE | `/admin/roles/{id}` | Role CRUD + permission matrix | admin |
| GET / POST | `/admin/auth-config/providers` | OAuth provider CRUD | admin |
| GET / PUT | `/admin/auth-config/mfa` | MFA settings per org | admin |
| GET | `/admin/features` | List feature flags with env overrides | admin |
| PUT | `/admin/features/{key}` | Toggle feature flag | admin |
| GET / PUT | `/admin/org-settings` | Org theming (logo, colour, name) | admin |

**Status:** ✅ Users, roles, features complete; auth-config providers partially complete

### 2.3 `dashboards` — `/dashboards`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/dashboards` | List dashboards visible to user's role | viewer |
| POST | `/dashboards` | Create dashboard config | admin |
| GET / PUT / DELETE | `/dashboards/{id}` | Dashboard CRUD | admin |
| GET / PUT | `/dashboards/{id}/permissions` | Per-dashboard access grants | admin |
| GET / PUT | `/dashboards/{id}/filters` | Filter definitions with user-attribute mapping | admin |
| POST | `/dashboards/{id}/embed-token` | Generate Power BI embed token | viewer |
| POST | `/dashboards/{id}/tableau-jwt` | Generate Tableau Connected App JWT | viewer |

**Status:** 🚧 CRUD complete; embed token endpoints in progress

### 2.4 `embed` — `/embed`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/embed/powerbi/workspaces` | List Power BI workspaces via service principal | admin |
| GET | `/embed/powerbi/workspaces/{id}/reports` | List reports / dashboards / apps | admin |
| GET | `/embed/tableau/workbooks` | List Tableau workbooks via REST API | admin |
| GET | `/embed/tableau/workbooks/{id}/views` | List views with thumbnail URLs | admin |

**Status:** 🚧 In progress

### 2.5 `pages` — `/pages`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/pages` | List pages accessible to current role | viewer |
| GET | `/pages/{slug}` | Page HTML content | viewer |
| GET / POST | `/admin/pages` | List / create custom HTML pages | admin |
| GET / PUT / DELETE | `/admin/pages/{id}` | Page CRUD | admin |
| GET | `/admin/pages/{id}/versions` | Version history (body snapshots) | admin |
| POST | `/admin/pages/{id}/versions/{vId}/restore` | Restore to earlier version | admin |

**Status:** 🚧 In progress

### 2.6 `streamlit` — `/streamlit`

| Method | Path | Description | Role |
|---|---|---|---|
| POST | `/streamlit` | Upload `.py` + `requirements.txt`, start app | admin |
| GET | `/streamlit` | List apps with status | admin |
| GET | `/streamlit/{id}/status` | Process health (HTTP ping to port) | admin |
| PUT | `/streamlit/{id}/restart` | Kill + relaunch | admin |
| DELETE | `/streamlit/{id}` | Stop + remove files from object storage | admin |

Port pool: `STREAMLIT_PORT_START`–`STREAMLIT_PORT_END` (default 8501–8600).

**Status:** 🚧 In progress

### 2.7 `chat` — `/chat`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/chat` | SSE stream: NL question → SQL → streamed result + explanation | analyst |
| GET | `/chat/history` | Past conversation turns | analyst |
| DELETE | `/chat/history` | Clear conversation history | analyst |

**Status:** 🚧 In progress

### 2.8 `exports` — `/exports`

| Method | Path | Description | Role |
|---|---|---|---|
| POST | `/exports` | Generate CSV / XLSX / PDF from a mart query | analyst |
| GET | `/exports` | Export job history (paginated) | analyst |
| GET | `/exports/{id}` | Job status + presigned download URL | analyst |
| GET / POST | `/exports/schedules` | List / create scheduled exports | analyst |
| GET / PUT / DELETE | `/exports/schedules/{id}` | Schedule CRUD + cron expression | analyst |

**Status:** 🚧 In progress

### 2.9 `pipelines` — `/pipelines`

All routes proxied to `PREFECT_API_URL` via `httpx.AsyncClient`. Requires `admin` role.

| Proxied path | Purpose |
|---|---|
| `/pipelines/flow-runs` | List / filter flow runs |
| `/pipelines/deployments` | List deployments + enable/disable |
| `/pipelines/deployments/{id}/create_flow_run` | Manual trigger with JSON parameters |
| `/pipelines/work-pools` | Work pool management |
| `/pipelines/work-queues` | Work queue management |

**Status:** 🚧 In progress

### 2.10 `notifications` — `/notifications` + pipeline notification routes

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/notifications/prefs` | Per-user channel preferences | viewer |
| PUT | `/notifications/prefs/{id}` / `/notifications/prefs/bulk` | Update preferences | viewer |
| GET / PUT | `/notifications/org-defaults` | Org-level defaults for new users | admin |
| GET/POST/PUT/DELETE | `/notification-groups[/{id}]` | Reusable destination groups (webhooks + email/SMS users) | admin |
| GET | `/notification-recipients` | Org users for email/SMS pickers | admin |
| GET / PUT | `/data-pipelines/{id}/notifications` | Per-connection run-notification config | admin |
| POST | `/data-pipelines/{id}/notifications/test` | Send a test to configured groups | admin |
| GET | `/data-pipelines/{id}/notification-status` | Non-sensitive badge data | viewer w/ access |
| GET / POST | `/data-pipelines/{id}/conditions` | Condition checks on a connection | admin |
| PUT / DELETE | `/notification-conditions/{id}` | Update/delete a condition | admin |
| POST | `/notification-conditions/{id}/check` | Dry-run a condition (no alert/state change) | admin |

**Status:** ✅ Complete

### 2.11 `lineage` — `/lineage`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/lineage/graph` | dbt manifest → full DAG (nodes + edges) | admin |
| GET | `/lineage/models/{name}` | Upstream + downstream lineage for one model | admin |

Reads `DBT_ARTIFACTS_PATH/manifest.json`. Set `DBT_ARTIFACTS_PATH` to the dbt `target/` directory.

**Status:** 🚧 In progress

### 2.12 `governance` — `/governance`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/governance/catalog` | Table and column browser with descriptions | admin |
| GET | `/governance/pii-tags` | PII tag matrix across warehouse columns | admin |
| POST / DELETE | `/governance/pii-tags` | Tag / untag a column | admin |
| GET | `/governance/audit-log` | Data access audit log (paginated) | admin |
| GET | `/governance/quality` | dbt test results per model (from ops schema) | admin |

**Status:** 🚧 In progress

### 2.13 `backups` — `/backups`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/backups` | Backup history (both databases) | superadmin |
| POST | `/backups` | Trigger manual `pg_dump` to object storage | superadmin |
| POST | `/backups/{id}/restore` | Restore from backup (dry-run → confirm → apply) | superadmin |

**Status:** 🚧 In progress

### 2.14 `retention` — `/retention`

| Method | Path | Description | Role |
|---|---|---|---|
| GET / POST | `/retention` | List / create retention policies | admin |
| GET / PUT / DELETE | `/retention/{id}` | Policy CRUD | admin |
| POST | `/retention/{id}/dry-run` | Preview rows to be deleted (no DB changes) | admin |
| POST | `/retention/{id}/apply` | Execute deletion after dry-run approved | admin |

`auto_apply=False` is the hard default. `apply` requires a `dry_run_id` from a preceding dry-run call.

**Status:** ✅ Complete

### 2.15 `data` — `/data`

| Method | Path | Description | Role |
|---|---|---|---|
| GET | `/data/tables` | List marts tables (governance-denied tables omitted) | viewer |
| GET | `/data/tables/{table}` | Paginated mart table query; governance rules deny/mask columns | viewer |
| GET | `/data/freshness` | Approximate marts last-updated (pg_stat_user_tables) | viewer |

All queries enforce `WHERE org_id = :org_id` via `services/data_query.py`. Access is logged to `access_audit_log`.

**Status:** 🚧 In progress

---

## 3. Service Layer

```
api/app/services/
├── crypto.py                   Fernet encrypt/decrypt; bcrypt hash/verify; TOTP gen/verify
├── user.py                     User + role CRUD, invitation flow, role assignment
├── auth_config.py              OAuth provider config CRUD; MFA settings per org
├── ai_chat.py                  LlamaIndex NLSQLTableQueryEngine + Claude SSE streaming
├── data_query.py               Org-scoped mart query builder; WHERE org_id enforced
├── export_generator.py         CSV / XLSX / PDF generation from mart queries
├── lineage_graph.py            Parses dbt manifest.json → nodes + edges
├── governance_catalog.py       Catalog reads; PII tag CRUD
├── backup_service.py           pg_dump invocation; object storage upload/download
├── retention_service.py        Policy evaluation; dry-run row counts; DELETEs
├── streamlit_manager.py        Port pool; asyncio subprocess lifecycle; venv isolation
├── embedders/
│   ├── powerbi.py              AAD client-credentials grant → embed token; Redis cache
│   └── tableau.py              Connected App JWT signing; Tableau REST view discovery
└── notifications/
    ├── dispatcher.py           Routes events to enabled channels; reads user preferences
    ├── email.py                SMTP / SendGrid adapter
    ├── slack.py                Slack Web API chat.postMessage adapter
    ├── teams.py                Teams incoming webhook adapter
    ├── gchat.py                Google Chat webhook adapter
    └── sms.py                  Twilio REST adapter
```

---

## 4. Database Schema

### 4.1 Application database (`biplatform_app`) — 26 tables

**Identity and access:**

| Table | Key columns |
|---|---|
| `orgs` | `id`, `name`, `slug`, `created_at` |
| `users` | `id`, `org_id`, `email`, `password_hash`, `totp_secret` (encrypted), `is_active` |
| `roles` | `id`, `org_id`, `name`, `description` |
| `permissions` | `id`, `name`, `resource`, `action` |
| `role_permissions` | `role_id`, `permission_id` |
| `user_roles` | `user_id`, `role_id` |

**Auth configuration:**

| Table | Key columns |
|---|---|
| `auth_provider_configs` | `id`, `org_id`, `provider`, `client_id`, `client_secret` (encrypted), `config` (JSONB) |
| `mfa_settings` | `org_id`, `totp_required`, `email_otp_enabled`, `grace_period_days` |

**Features and settings:**

| Table | Key columns |
|---|---|
| `feature_flags` | `org_id`, `feature_key`, `enabled`, `config` (JSONB), `updated_at` |
| `org_settings` | `org_id`, `logo_url`, `primary_colour`, `app_name` |

**Dashboards:**

| Table | Key columns |
|---|---|
| `dashboard_configs` | `id`, `org_id`, `name`, `type`, `settings` (JSONB), `required_role` |
| `dashboard_permissions` | `dashboard_id`, `user_id`, `role_id` |
| `dashboard_filters` | `id`, `dashboard_id`, `filter_key`, `user_attribute`, `default_value` |

**Custom content:**

| Table | Key columns |
|---|---|
| `custom_pages` | `id`, `org_id`, `slug`, `title`, `body`, `required_role` |
| `custom_page_versions` | `id`, `page_id`, `body`, `created_at`, `created_by` |
| `streamlit_apps` | `id`, `org_id`, `name`, `port`, `status`, `storage_path` |
| `streamlit_deploy_logs` | `id`, `app_id`, `event`, `message`, `created_at` |
| `custom_react_dashboards` | `id`, `org_id`, `key`, `label`, `param_definitions` (JSONB) |

**Operations:**

| Table | Key columns |
|---|---|
| `exports` | `id`, `org_id`, `user_id`, `format`, `status`, `storage_path`, `created_at` |
| `export_schedules` | `id`, `org_id`, `cron`, `table_name`, `format`, `delivery_target` |
| `notification_preferences` | `user_id`, `org_id`, `channel`, `event_type`, `enabled`, `config` (webhook_url for slack/teams/gchat) |
| `notification_groups` | `id`, `org_id`, `name`, `channels` (webhook URLs + email/SMS user ids) |
| `pipeline_notification_configs` | `pipeline_connection_id`, toggles, templates, `poll_frequency_minutes`, group ids, overrides, poller bookkeeping |
| `notification_conditions` | `pipeline_connection_id`, `condition_type` (pipeline_idle \| data_freshness), `threshold_minutes`, freshness target (`warehouse_connection_id`, table, column), group ids, check state |
| `data_catalog_tags` | `id`, `org_id`, `schema_name`, `table_name`, `column_name`, `tag` |
| `backup_history` | `id`, `org_id`, `database`, `storage_path`, `size_bytes`, `created_at` |
| `retention_policies` | `id`, `org_id`, `table_pattern`, `max_age_days`, `last_dry_run_at` |
| `access_audit_log` | `id`, `org_id`, `user_id`, `resource`, `action`, `row_count`, `created_at` |

### 4.2 Warehouse database (`biplatform_warehouse`) — API read-only

| Schema | Purpose |
|---|---|
| `raw` | Bronze: ingested data mirrors — accessed only by ingestion + dbt |
| `staging` | Silver: typed, renamed, deduplicated — accessed only by dbt |
| `marts` | Gold: business-ready — accessed by API via `warehouse_reader` |
| `ops` | dbt run results, test outcomes, freshness — read by API lineage + governance |

---

## 5. Authentication Architecture

### 5.1 Credential login flow

```
POST /auth/token  {email, password, totp_code?}
    ▼
Look up user by email
Verify bcrypt(password, user.password_hash)
If org.mfa_settings.totp_required: verify TOTP code
    ▼
Generate JWT: {user_id, org_id, role, exp: now + ACCESS_TOKEN_TTL}
    ▼
Return {access_token, user_id, org_id, role, name, email}
```

### 5.2 OAuth exchange flow

```
Auth.js OAuth callback → POST /auth/oauth-exchange
    {provider, access_token, id_token}
    ▼
Verify token with provider JWKS
Find or provision user by email
Assign default role from org config
    ▼
Return platform JWT (same shape as credential flow)
```

### 5.3 Role enforcement

`require_role()` returns a FastAPI `Depends()` — never a decorator:

```python
_admin_dep = require_role("admin", "superadmin")

@router.get("/admin/features")
async def list_features(
    current_user: CurrentUser = Depends(_admin_dep),
    db: AsyncSession = Depends(get_app_db),
) -> list[dict]:
    ...
```

---

## 6. AI Chat Architecture

```
GET /chat?q=<question>   (SSE response — EventSource on the frontend)
    │
    ▼  LlamaIndex NLSQLTableQueryEngine
    │   - connects to biplatform_warehouse.marts via warehouse_reader
    │   - table context: all mart schemas + column descriptions from catalog
    │   - query timeout: 30 seconds; row limit: 10,000
    │
    ▼  Anthropic claude-sonnet-4-6
    │   - generates SQL from natural language
    │   - streams explanation tokens via Anthropic SSE
    │
    ▼  Execute SQL against marts (SELECT only — no DML via warehouse_reader)
    │
    ▼  Stream: SQL result rows + explanation tokens → EventSource in ChatWindow.tsx
```

**Why EventSource directly to FastAPI:** Next.js API routes buffer the full response before forwarding, which breaks SSE streaming. The frontend opens `EventSource` to `NEXT_PUBLIC_API_URL/chat` — not through a Next.js route.

---

## 7. Embed Architecture

### 7.1 Power BI (service principal path)

```
POST /dashboards/{id}/embed-token
    ▼
Load auth_provider_configs (provider='powerbi_sp')
Decrypt client_secret via Fernet
    ▼
AAD client_credentials grant → AAD access token
Power BI REST: POST /generateToken
    {reports: [{id, accessLevel}], datasets: [{id}]}
Cache in Redis (TTL = token_expiry - 60s)
    ▼
Return {embed_url, access_token, expiry}
```

`PowerBIEmbed.tsx` schedules a refresh via `setInterval` at TTL − 120 seconds.

### 7.2 Tableau Connected App

```
POST /dashboards/{id}/tableau-jwt
    ▼
Load auth_provider_configs (provider='tableau_connected_app')
Decrypt RS256 private key
    ▼
Sign JWT: {iss: client_id, sub: user.email, exp: now+900,
           aud: 'tableau', scope: ['tableau:views:embed']}
    ▼
Return {token, expiry, view_url}
```

`TableauEmbed.tsx` passes filter values to the Tableau JS API after the view loads.

### 7.3 Streamlit proxy

Streamlit apps are not publicly accessible. The Next.js route `app/api/streamlit/[appId]/[...path]/route.ts` reverse-proxies requests to `localhost:{port}`. The proxy adds the session guard so users must be authenticated.

---

## 8. Notification System

Two cooperating layers share one set of delivery adapters
(`services/pipeline_notifications.py`: Slack/Teams/Google Chat webhooks, SMTP
email, Twilio SMS):

1. **Org destination groups** — admins define `NotificationGroup`s (webhook
   URLs + email/SMS users) and attach them to pipeline-notification configs and
   condition checks. Delivery via `send_to_groups`.
2. **Per-user preferences** — each user opts into event types per channel
   (`NotificationPreference`). Delivery via `dispatcher.dispatch_event`.

### 8.1 Dispatch pattern

Any service dispatches events without knowing who is subscribed:

```python
await dispatch_event(
    event_type="pipeline_failure",
    payload={"subject": "…", "message": "…"},   # extra keys render as key: value lines
    org_id=current_user.org_id,                 # None = no-op
)
```

`dispatcher.py` reads enabled preferences for the org + event type, filters
channels to `NOTIFICATION_CHANNELS_ENABLED`, rate-limits (1 per user per event
type per 5 min via Redis), delivers through the shared adapters, and appends an
audit entry to the `notifications:{channel}` Redis stream. Email/SMS resolve
the user's address/phone; webhook channels (slack/teams/gchat) read
`webhook_url` from the preference's `config` JSON and are skipped without one.

### 8.2 Notification event types

| Event | Emitted by |
|---|---|
| `pipeline_failure` / `pipeline_success` | Pipeline poller, per new terminal run |
| `pipeline_idle` | Condition checker — no run within threshold |
| `data_freshness` | Condition checker — `MAX(timestamp_column)` older than threshold |
| `backup_complete` / `backup_failed` | `backup_service.trigger_backup` |
| `export_ready` / `export_failed` | Reserved — pending an export job executor (jobs are created `running`; no background executor exists yet) |

### 8.3 Background evaluation

`services/pipeline_poller.py` is the API's only periodic runner (asyncio task
started in the `main.py` lifespan; 60s tick; Redis lock so one worker polls per
tick). Each tick it (a) diffs provider runs against every due
`PipelineNotificationConfig` and (b) evaluates due `NotificationCondition`
checks via `services/condition_checker.py`. Condition alerts are
state-transition based — one alert on trip, one on recovery (optional), never
re-alerts while still triggered; probe errors are recorded without flipping
state. Freshness probes run through `warehouse_inspector.run_select` against
any org warehouse connection, or the built-in marts engine when
`warehouse_connection_id` is NULL.

---

## 9. Feature Flag System

### 9.1 Precedence

```
FEATURE_* env var  (highest priority)
    ↓ if not set
feature_flags DB row for org
    ↓ if missing
false (safe default)
```

### 9.2 Key → env var mapping

| Feature key | Env var |
|---|---|
| `chat` | `FEATURE_CHAT` |
| `exports` | `FEATURE_EXPORTS` |
| `custom_pages` | `FEATURE_CUSTOM_PAGES` |
| `prefect_monitor` | `FEATURE_PREFECT_MONITOR` |
| `lineage` | `FEATURE_LINEAGE` |
| `governance` | `FEATURE_GOVERNANCE` |
| `backups` | `FEATURE_BACKUPS` |
| `retention` | `FEATURE_RETENTION` |
| `embed.powerbi` | `FEATURE_EMBED_POWERBI` |
| `embed.tableau` | `FEATURE_EMBED_TABLEAU` |
| `embed.custom_react` | `FEATURE_EMBED_CUSTOM_REACT` |
| `embed.streamlit` | `FEATURE_EMBED_STREAMLIT` |

### 9.3 Implementation detail

`settings.feature_overrides` reads `os.getenv()` at call time (not pydantic fields) so that `monkeypatch.setenv()` works in tests without module reload. Redis cache invalidated on every toggle.

---

## 10. Implementation Status

| Router | Status | Notes |
|---|---|---|
| `auth` | ✅ Complete | All flows working |
| `admin` — users/roles | ✅ Complete | CRUD + invite |
| `admin` — features | ✅ Complete | Env override + Redis cache; 11 unit tests |
| `admin` — auth-config | 🚧 In progress | Provider CRUD partial |
| `dashboards` | 🚧 In progress | CRUD done; embed tokens in progress |
| `embed` | 🚧 In progress | Workspace/report discovery in progress |
| `pages` | 🚧 In progress | CRUD done; version history partial |
| `streamlit` | 🚧 In progress | Manager implemented; routes partial |
| `chat` | 🚧 In progress | LlamaIndex wired; streaming route partial |
| `exports` | 🚧 In progress | CSV/XLSX done; PDF + schedules in progress |
| `pipelines` | 🚧 In progress | Proxy works; wiring partial |
| `notifications` | ✅ Complete | Prefs + org defaults; dispatcher delivers via real adapters (5 channels), rate-limited, `NOTIFICATION_CHANNELS_ENABLED` honored |
| pipeline notifications | ✅ Complete | Groups, per-connection configs, poller, condition checks (idle + freshness) with dry-run endpoint |
| `lineage` | 🚧 In progress | Manifest reader done; graph endpoint partial |
| `governance` | ✅ Complete | Catalog/PII/quality/audit gated by `governance.*` perms; role-based policies (deny/mask rules) enforced in `/data` + AI chat |
| `backups` | 🚧 In progress | pg_dump + backup_complete/backup_failed events; restore partial |
| `retention` | ✅ Complete | Policy CRUD, dry-run enforced before apply |
| `data` | ✅ Complete | Paginated queries, freshness endpoint, governance enforcement (deny/mask), audit logging |
| exports (execution) | 🔲 Not started | Job/schedule CRUD exists; no background executor runs jobs — `export_ready`/`export_failed` events reserved |

---

## 11. Testing Plan

### 11.1 Unit tests structure

```
api/tests/
├── conftest.py                        # mock_admin_user, mock_db_session (AsyncMock),
│                                      # autouse permission-grant patcher
├── routers/
│   ├── test_features.py               # Env override, list, toggle
│   ├── test_portal.py                 # Feature gating: org flag × permission × grant matrix
│   ├── test_warehouses.py             # Connection CRUD + role-grant sharing
│   ├── test_data_dict.py              # Dictionary CRUD, exclusions, sharing
│   ├── test_erd.py / test_data_lineage.py / test_bi_connections.py
│   ├── test_data_pipelines.py         # Provider CRUD, sharing, run listing
│   ├── test_pipeline_notifications.py # Groups + per-connection config CRUD
│   ├── test_notification_conditions.py# Condition CRUD, validation, dry-run check
│   ├── test_governance_policies.py    # Policy/rule/role CRUD, identifier validation
│   └── test_clients.py / test_projects.py / test_gantt.py / test_kanban.py / …
└── services/
    ├── test_ai_chat_access.py         # Dict vs warehouse grant separation
    ├── test_governance_rules.py       # Rule resolution, SQL checks, masking
    ├── test_condition_checker.py      # Idle/freshness probes, transition alerts
    ├── test_dispatcher.py             # Channel filter, rate limit, adapter delivery
    └── test_project_ai.py / test_lineage_ai.py
```

### 11.2 Integration tests

Marked `@pytest.mark.integration`, require `TEST_DATABASE_URL`:

```
api/tests/integration/
├── test_auth_flow.py       # Full token issuance against real DB
├── test_data_query.py      # org_id filter against test warehouse
└── test_migrations.py      # alembic upgrade/downgrade round-trip
```

### 11.3 Running tests

```bash
cd api
pip install -e ".[dev]"

pytest                                         # unit tests only
pytest -m integration                          # needs TEST_DATABASE_URL
pytest tests/routers/test_features.py -v      # specific file
pytest --cov=app --cov-report=term-missing     # coverage report
```

### 11.4 Key test patterns

```python
# AsyncMock DB session
@pytest.fixture
def mock_db():
    session = AsyncMock(spec=AsyncSession)
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    return session

# Override FastAPI dependencies per test
app.dependency_overrides[get_app_db] = lambda: mock_db
app.dependency_overrides[require_role("admin")] = lambda: admin_user
```

---

## 12. Additional Features

### 12.1 API rate limiting

Per-org and per-user rate limits using Redis sliding window counters. Middleware enforces limits before JWT validation; returns `429 Too Many Requests` with `Retry-After` header. Limits: 1,000 req/min per org, 100 req/min per user, 10 req/min for `/chat`.

### 12.2 Outbound webhooks

Complement the inbound webhook receiver with outbound delivery. `webhook_subscriptions` table: `org_id`, `event_type`, `target_url`, `secret`. `dispatcher.py` POSTs events with HMAC-SHA256 signature so receiving systems can verify authenticity.

### 12.3 Query result caching

Cache frequently-run mart queries in Redis (`query:{org_id}:{hash(sql)}`). Invalidated when the mart's `_loaded_at` advances past the cached result's timestamp. Reduces DB load for high-traffic dashboards.

### 12.4 OpenTelemetry tracing

Instrument all request handlers and service calls with OpenTelemetry spans. Export to Jaeger or Azure Monitor. Enables trace-level debugging of slow queries, failed embed token fetches, and notification delivery failures.

### 12.5 Streaming exports

Replace the materialise-then-download model with `StreamingResponse` + `csv.writer` writing directly to the HTTP response body. Avoids holding large exports in memory. Required for tables exceeding 100k rows.

### 12.6 dbt Semantic Layer integration

Expose `GET /metrics/{name}` backed by dbt MetricFlow definitions. Enables consistent, pre-defined metric values (MRR, CAC, churn rate) across AI chat, exports, and dashboards without per-endpoint SQL queries.

### 12.7 Async task queue

For long-running operations (PDF export, database restore), move from inline async handlers to a Celery / Prefect task queue backed by Redis. Return a `202 Accepted` with a job ID; clients poll `GET /exports/{id}` for status.
