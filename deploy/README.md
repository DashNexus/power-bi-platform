# Deployment

Azure Container Apps, Azure SQL, and Blob Storage, provisioned by Bicep.

---

## Architecture

```
                    ┌──────────────────────────────┐
   browser ────────▶│ pbip-<env>-app   (port 3000) │  Next.js, standalone build
                    └──────────────┬───────────────┘
                                   │ NEXT_PUBLIC_API_URL (baked at build time)
                    ┌──────────────▼───────────────┐
                    │ pbip-<env>-api   (port 8000) │  FastAPI + ODBC Driver 18
                    └───┬───────────────────────┬──┘
                        │                       │
         ┌──────────────▼────────┐   ┌──────────▼─────────────┐
         │ biplatform_app        │   │ Blob Storage (assets)  │
         │ biplatform_warehouse  │   │ exports, avatars, logos│
         │ Azure SQL, serverless │   └────────────────────────┘
         └───────────────────────┘
```

Container Apps rather than App Service: the API image carries the ODBC driver
and runs as a non-root user, and the two services scale independently on one
internal network.

## What the template creates

| Resource | Name | Notes |
|---|---|---|
| Log Analytics workspace | `pbip-<env>-logs` | 30-day retention; both apps stream here |
| SQL logical server | `pbip-<env>-sql` | TLS 1.2 floor, Azure-services firewall rule |
| SQL databases | `biplatform_app`, `biplatform_warehouse` | `GP_S_Gen5_1` serverless, auto-pause after 60 min |
| Storage account | `pbip<env>stor` | Private `assets` container |
| Redis | `pbip-<env>-redis` | **Only when `deployRedis: true`** |
| Container Apps environment | `pbip-<env>-env` | |
| Container apps | `pbip-<env>-api`, `pbip-<env>-app` | External ingress, system-assigned identity |

Serverless SQL is the default because the application database is small and
mostly metadata; auto-pause means a dev environment costs nothing overnight. A
production environment should move to a provisioned tier — an auto-paused
database adds a cold-start delay to the first request after idle.

## Quick Start

```bash
az login
cp deploy/azure/parameters.dev.json deploy/azure/parameters.prod.json  # for a second env
# Replace every REPLACE_ME in the parameters file first — the script refuses otherwise.

./deploy/scripts/deploy.sh -g my-resource-group -r myacr -e dev
```

The script provisions, builds both images in ACR, rolls them out, and migrates.
Re-running is safe: the Bicep deployment is incremental and the migration is
idempotent.

### Why infrastructure is provisioned before the images are built

`NEXT_PUBLIC_API_URL` is **inlined into the browser bundle at build time** — by
the time the container runs, the value is already compiled into the JavaScript
the browser downloads. So the API's URL has to exist before the frontend image
is built, which means provisioning first and building second. A consequence
worth knowing: **a frontend image cannot be promoted between environments.**
Each one is bound to the API URL it was built against.

## Migrations

```bash
./deploy/scripts/migrate.sh -g my-rg -e dev                    # upgrade head
./deploy/scripts/migrate.sh -g my-rg -e dev -c "current"       # what is deployed?
./deploy/scripts/migrate.sh -g my-rg -e dev -c "downgrade -1"  # step back one
```

These run `alembic` **inside the deployed API container**, not from a laptop.
The container already has the ODBC driver, the connection string, and an egress
IP the SQL firewall allows — running it locally would mean opening the firewall
to a developer address and then remembering to close it.

## GitHub Actions

| Workflow | Trigger | Does |
|---|---|---|
| `ci.yml` | push, PR | Lint, typecheck, unit tests, a real migration against SQL Server, and both image builds |
| `deploy.yml` | push to `main`, manual | Provision → build → migrate → roll out → smoke-test |

`deploy.yml` authenticates with **OIDC federation**, so no service-principal
secret is stored. Configure the federated credential on the app registration,
then set these repository secrets:

| Secret | Value |
|---|---|
| `AZURE_CLIENT_ID` | App registration (client) ID |
| `AZURE_TENANT_ID` | Directory (tenant) ID |
| `AZURE_SUBSCRIPTION_ID` | Target subscription |
| `AZURE_RESOURCE_GROUP` | Target resource group |
| `ACR_NAME` | Registry name, without `.azurecr.io` |
| `SQL_ADMIN_PASSWORD` | SQL administrator password |
| `NEXTAUTH_SECRET` | `openssl rand -base64 32` |
| `TOTP_ENCRYPTION_KEY` | A Fernet key |

The `api-integration` CI job runs the migration against a real SQL Server
container **twice**. Once proves the schema is creatable on the deployment
target — the two failures it catches (a `String` with no length, a second
cascade path) are both invisible on PostgreSQL. Twice proves the seed is
idempotent, which is what makes a redeploy safe.

## Scaling

`maxReplicas` on the API is pinned to **1 while `deployRedis` is false**, and
that is a correctness constraint rather than a cost one: the pipeline poller
runs on a timer inside the API process, and without the Redis lock every replica
would run the same tick and send the same alert several times. Set
`deployRedis: true` before raising it.

The frontend is stateless and scales freely.

## Hardening before production

The template optimises for a working first deploy. Before real data:

- **Replace the `0.0.0.0` SQL firewall rule with VNet integration.** The
  Azure-services rule admits any Azure tenant's egress, not just yours.
- **Move secrets to Key Vault** and reference them from Container Apps, rather
  than passing them as deployment parameters that persist in deployment history.
- **Use a managed identity for SQL** instead of an administrator password.
- **Move off serverless SQL** if cold starts matter.
- **Change the seeded `admin@example.com` password** — the migration creates it
  with a known default so the first sign-in works at all.
