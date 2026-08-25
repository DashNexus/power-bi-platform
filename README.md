# Power BI Platform

A self-service portal for publishing Power BI reports and embedded pages to an
organisation, with the governance surface around them: a data dictionary,
warehouse and BI connections, Azure Data Factory pipeline monitoring with
alerting, an audit log, a revertible change history, and user/role management.

Runs on **Azure SQL** (or PostgreSQL), deploys to **Azure Container Apps**.

---

## Architecture

Two independently deployable layers, one database each way:

| Directory | Stack | Purpose |
|---|---|---|
| `api/` | FastAPI, Python 3.12 | Every endpoint, the schema, and all access control |
| `application/` | Next.js 15, TypeScript | Portal, dashboards, and the admin console |
| `deploy/` | Bicep + bash | Azure infrastructure and deployment scripts |

**`biplatform_app`** (`APP_DATABASE_URL`) holds users, roles, dashboards, pages,
connections, the audit log, and the change ledger. **`biplatform_warehouse`**
(`WAREHOUSE_DATABASE_URL`) is read-only to the API and holds the `marts` schema
the data dictionary describes and exports read from.

### What this build does *not* have

Deliberately absent, so nobody goes looking: AI chat and the assistant panel,
ERDs, data lineage graphs, timelines, manual datasets, tickets, project
planning, time tracking, billing, backups, retention policies, Streamlit apps,
API keys, and the organisation-settings console. Embeds are **Power BI reports
and page URLs only**; the pipeline provider is **Azure Data Factory only**;
the identity provider is **Microsoft Entra ID only**.

---

## Quick Start

Requires Python 3.12, Node 22, and the
[Microsoft ODBC Driver 18](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server).
Docker is needed **only** if you have no SQL Server to point at.

```bash
./scripts/dev.sh          # bash, macOS/Linux, or Git Bash on Windows
.\scripts\dev.ps1         # PowerShell — same script, native entry point
```

That is the whole thing. It generates `.env` with fresh secrets on first run,
installs anything missing, starts Azure SQL Edge, creates both databases, applies
migrations, and runs the API and the frontend with prefixed logs. Ctrl+C stops
both servers and leaves the database up.

- App — <http://localhost:3000>, sign in as `admin@example.com` / `admin123`
- Swagger — <http://localhost:8000/docs>

Re-running is safe: every step checks before it acts.

### Which database it uses

Whatever `APP_DATABASE_URL` in `.env` names. If that server is already
reachable, Docker is never started — the container in `docker-compose.yml` is a
fallback, not the default.

The shipped default is a SQL Server on `localhost:1433`, database
`bi_platform_database`, login `biplatformadmin`. To use the throwaway container
instead, point the URL at `localhost:15433`; it creates the same login on first
start, so nothing else changes.

`WAREHOUSE_DATABASE_URL` is read-only and only ever reads the `marts` schema, so
it shares the application database by default. Re-point it at the real warehouse
when there is one.

| Flag | |
|---|---|
| `--check` | Run the preflight checks and exit, changing nothing |
| `--api-only` / `--app-only` | Run one server (the database still starts) |
| `--fresh` | Destroy the database volume and re-seed |
| `--force` | Kill whatever already holds port 8000 / 3000 |
| `--skip-install` | Skip the dependency check |

### Doing it by hand

```bash
cp .env.example .env                                                 # fill both secrets
openssl rand -base64 32                                              # NEXTAUTH_SECRET
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

cd api && pip install -e ".[dev]" && cd ../application && npm install && cd ..
docker compose up -d --wait mssql
cd api && alembic upgrade head && uvicorn app.main:app --reload --port 8000   # terminal 1
cd application && npm run dev                                                 # terminal 2
```

`NEXTAUTH_SECRET` must be **identical** in `.env` and `application/.env.local` —
the API verifies the JWT that Auth.js signs, and a mismatch signs users in and
then 401s every request after it.

---

## Reference

### Feature flags

Per-org, stored in the database. This build ships no admin page for them:
change one through `PUT /admin/features/{key}` (Swagger at `/docs`) or pin it
with a `FEATURE_*` environment variable, which overrides the stored value.

| Key | Gates |
|---|---|
| `dashboards` | Dashboard listing, detail, and admin CRUD |
| `custom_pages` | Custom HTML pages |
| `governance` | Data dictionary |
| `pipelines` | ADF connections, run monitoring, notifications |
| `exports` | SQL reports, their run log, and schedules |
| `embed.powerbi` | Power BI as a dashboard embed type |
| `embed.page` | URL/iframe page embeds |
| `pipelines.adf` | Azure Data Factory as a pipeline provider |

### Permissions

Access is decided by permission keys attached to roles, plus per-resource
grants — never by role level alone. `ROLE_HIERARCHY`
(`viewer < analyst < manager < admin < superadmin`) gates only the coarse admin
console. The seeded vocabulary is in `api/alembic/versions/001_initial.py`.

| Key | Grants |
|---|---|
| `dashboards.view` / `.manage` | See dashboards / create and edit them |
| `pages.view` / `.manage` | See custom pages / author them |
| `data_dictionary.view` / `.manage` | Read the dictionary / edit entries |
| `warehouses.view` / `.manage` | See warehouse connections / manage them |
| `bi_connections.view` / `.manage` | See BI connections / manage them |
| `pipelines.view` / `.manage` | See pipeline runs / manage connections |
| `exports.view` / `.create` | See exports / create them |
| `changes.view` | The org-wide change history |
| `audit.view` / `.manage` | Read the audit log / set retention and purge |

### SQL reports

A report runs one read-only query and delivers the result as CSV, XLSX, or PDF.

| Choice | Options |
|---|---|
| **Source** | A named warehouse connection, or the **operations database** (the one this application runs on). Operations-source reports are admin-only. |
| **When** | A cron expression, or nothing at all — a report with no schedule runs only when someone presses Run. |
| **Delivery** | Stored for download, or uploaded over SFTP. Email is built but not switched on — it needs SMTP credentials and a verified sender, so the option is disabled and the API refuses it. |

#### Reports cannot write

Four layers, weakest first. Only the last is airtight, and it is the one the
application cannot apply for you.

1. **Statement guard.** A single `SELECT` or `WITH … SELECT`, nothing else.
   Refused: writes, DDL, stacked statements, `SELECT … INTO`, system procedures
   (`sp_`/`xp_`/`pg_`), `OPENQUERY`/`OPENROWSET`/`OPENDATASOURCE`, `dblink`,
   large-object file functions, `FOR UPDATE`, and PostgreSQL's data-modifying
   CTEs (`WITH x AS (DELETE … RETURNING *) SELECT * FROM x` — a real write that
   leads with an allowed keyword). Checked when the report is saved **and**
   again by the worker immediately before execution, so a row that reached the
   database another way is still refused.
2. **Server-enforced read-only, on PostgreSQL.** The transaction is
   `SET TRANSACTION READ ONLY`, so the server rejects writes rather than the
   application predicting them. SQL Server has no equivalent.
3. **Unconditional rollback.** Every query runs in a transaction that is always
   rolled back — verified against SQL Server for `INSERT`, `UPDATE`, `DELETE`,
   `TRUNCATE`, `CREATE`/`ALTER`/`DROP TABLE`, and `CREATE INDEX`: none of them
   persisted.
4. **A read-only login.** See below.

**The rollback does not cover everything.** Sequence advances (`nextval`,
`setval`, `NEXT VALUE FOR`) are non-transactional on both engines, `dblink`
writes to a different server, and `lo_export` writes a file on the host — a
rollback undoes none of these. They are blocked at layer 1, which for them is
the only layer that applies.

**What is left.** A parser cannot see inside a function body. On PostgreSQL a
`VOLATILE` user-defined function can write, and on SQL Server a CLR function
can do anything the service account can. Layer 2 stops the PostgreSQL case;
nothing but a read-only login stops the SQL Server one. So:

```sql
-- Run against each database a report may read.
CREATE LOGIN report_reader WITH PASSWORD = '<a strong password>';
CREATE USER  report_reader FOR LOGIN report_reader;
ALTER ROLE   db_datareader ADD MEMBER report_reader;
-- db_datareader grants SELECT and nothing else. Do not add db_datawriter,
-- db_ddladmin, or db_owner.
DENY EXECUTE TO report_reader;
```

Then point the warehouse connection at `report_reader` instead of an
administrative login. With that in place, a write cannot happen even if every
layer above it were removed.

Reports against the operations database additionally refuse any table holding
credentials — including bracket-quoted forms such as `[dbo].[users]`, which is
what SSMS generates. That database is **not** scoped to one organisation: an
operations query sees every org's rows, which is why it takes an admin. It is
also the one source that cannot be given a read-only login without changing
`APP_DATABASE_URL`, which the application writes through.

Every execution is recorded in the run log with its row count, size, duration,
and error. **Runs and their files are kept for 30 days**
(`export_runner.RESULT_RETENTION_DAYS`), then purged; downloading an expired
result returns `410`. A run that outlives `STUCK_JOB_TIMEOUT` (30 minutes) is
failed automatically, and can be cancelled by hand before that.

**Test the query before saving it.** The report editor's *Test query* button
runs the definition once and shows the first rows, how long it took, and the
database's own error if it fails. Nothing is saved, delivered, or logged, and a
test uses a shorter timeout than a real run — so testing a runaway query costs
seconds rather than minutes.

What one report may cost is capped in four places, all configurable:

| Setting | Default | Bounds |
|---|---|---|
| `EXPORT_QUERY_TIMEOUT_SECONDS` | 300 | How long the *server* runs the query before abandoning it |
| `EXPORT_PREVIEW_TIMEOUT_SECONDS` | 30 | The same, for a test |
| `EXPORT_MAX_ROWS` | 100000 | Rows in a full export |
| `EXPORT_MAX_CELLS` | 2000000 | Rows × columns, which is what actually bounds memory |

The timeout is enforced by the database, not by us: cancelling on our side would
leave the query running and still consuming the warehouse. One run per report at
a time, and at most five jobs per worker tick, run one after another.

Execution happens in a background worker on a 30-second tick, not in the
request — pressing Run returns a *pending* job. The worker is the second of the
API's two periodic runners, so **more than one API replica needs Redis** or
both will run the same report.

### Key environment variables

| Variable | Notes |
|---|---|
| `APP_DATABASE_URL` | `mssql+aioodbc://…?driver=ODBC+Driver+18+for+SQL+Server` or `postgresql+asyncpg://…` |
| `WAREHOUSE_DATABASE_URL` | Read-only; the `marts` schema |
| `NEXTAUTH_SECRET` | Shared between both layers |
| `TOTP_ENCRYPTION_KEY` | Fernet key for TOTP secrets and stored client secrets |
| `AZURE_AD_CLIENT_ID` / `_SECRET` / `_TENANT_ID` | Entra SSO; all three or none |
| `REDIS_URL` | **Optional** — see below |
| `STORAGE_URI` | `az://` \| `s3://` \| `gcs://` \| `file://` |
| `NEXT_PUBLIC_API_URL` | Inlined into the browser bundle at *build* time |

The complete list is `api/app/config.py`; `.env.example` documents each one.

### Is Redis required?

**No, not for a single node.** It has two uses, and both degrade gracefully when
it is unreachable:

- the pipeline poller's cross-worker lock (`services/pipeline_poller.py`), and
- per-user notification rate limiting (`services/notifications/dispatcher.py`).

Add it once you run **more than one API replica** — without it, each replica
runs the poll tick and the same alert goes out several times. The Bicep template
keeps `maxReplicas` at 1 while `deployRedis` is false for exactly that reason.

---

## Deployment

```bash
az login
./deploy/scripts/deploy.sh -g my-resource-group -r myacr -e dev
```

That provisions the infrastructure, builds both images in ACR, rolls them out,
and runs the migration. See [deploy/README.md](deploy/README.md) for what it
creates, the GitHub Actions equivalent, and the secrets each needs.

---

## Running Tests

```bash
make test              # both layers
make test-api          # API unit tests — mocked DB, nothing to start
make test-app          # frontend unit tests
make lint              # ruff + mypy + eslint
make typecheck         # tsc --noEmit
```

Integration tests are opt-in: `cd api && pytest -m integration` (needs
`TEST_DATABASE_URL`).

**Unit tests are necessary, not sufficient.** The two failure modes that reach a
deployment are both server-side and invisible to a mocked session: a `String`
column with no length, and a second cascade path between two tables. Both are
pinned by `api/tests/test_schema_portability.py`, and CI additionally runs the
real migration against a real SQL Server — twice, to prove the seed is
idempotent.

---

## Troubleshooting

**`Can't open lib 'ODBC Driver 18 for SQL Server'`** — the driver is not
installed on the host. Install it from Microsoft's package feed
([Linux](https://learn.microsoft.com/sql/connect/odbc/linux-mac/installing-the-microsoft-odbc-driver-for-sql-server),
[Windows](https://learn.microsoft.com/sql/connect/odbc/download-odbc-driver-for-sql-server)),
or run the API in its container, which already has it. Check what is present
with `python -c "import pyodbc; print(pyodbc.drivers())"`.

**`SSL Provider: certificate verify failed`** — Driver 18 encrypts by default
and the local container uses a self-signed certificate. Append
`&TrustServerCertificate=yes` to the local URL. Never do this against Azure SQL:
there the certificate is real and the error means something is wrong.

**`CompileError: VARCHAR requires a length on dialect mssql`** — a model gained
a `String` column with no length. Give it one; `tests/test_schema_portability.py`
catches this before deploy.

**`Introducing FOREIGN KEY constraint ... may cause cycles or multiple cascade
paths`** — a new foreign key added a second `ON DELETE CASCADE` route between
two tables. SQL Server rejects that (error 1785) where PostgreSQL allows it.
Keep the cascade on the owning parent only and clear the rest explicitly — see
`api/app/services/principal_cleanup.py`.

**`Login failed for user 'sa'` while the container reports healthy** — something
other than the container is answering the port. A Windows box with SQL Server
installed can hold several ports at once, and Windows lets that instance and the
Docker proxy both bind the same one; the local instance wins. `scripts/dev.sh`
detects this and names the process. Fix it by setting `MSSQL_HOST_PORT` in `.env`
to a free port and changing the port in `APP_DATABASE_URL` and
`WAREHOUSE_DATABASE_URL` to match. Check who owns a port with
`netstat -ano | findstr :15433`.

**`greenlet_spawn has not been called` from Alembic** — the URL names an async
driver that `api/alembic/env.py` has no sync counterpart for. Migrations run
synchronously; add the mapping to `_SYNC_DRIVERS` there.

**`Incorrect syntax near '1'`** — a query used `column.is_(True)`, which renders
as `IS 1` on SQL Server, and T-SQL's `IS` accepts only NULL. Use `is_true()` /
`is_false()` from `app/sql_compat.py`.

**`MSSQL requires an order_by when using an OFFSET`** — a paginated query has no
`ORDER BY`. Add one; `tests/test_schema_portability.py` catches these.

**Login succeeds, then every API call 401s** — `NEXTAUTH_SECRET` differs between
the frontend and the API. The API verifies the JWT Auth.js signed, so the two
must match exactly.

**The Power BI embed renders blank** — the service principal has no access to
the workspace. Add it to the workspace as a Member, and enable *Allow service
principals to use Power BI APIs* in the tenant settings. `POST
/embed/powerbi/test-connection` reports which of the two is missing.

**A dashboard shows the provider's sign-in page instead of the report** — a
pasted *share* link is not an embed URL. `publicEmbedUrl.ts` converts the common
ones at render time; verify with `curl -D -` that the URL returns `200` and not
a `302`.
