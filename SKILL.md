# Power BI Platform — Commit Message Format

```
<type>(<scope>): <summary>      ← imperative mood, ≤72 chars, no trailing period
<body>                          ← optional; why, not what; wrap at 72
<footer>                        ← optional; BREAKING CHANGE:, Closes #n, Co-authored-by:
```

**Types:** `feat` (new capability), `fix` (was broken, now isn't), `refactor` (no behaviour change), `perf`, `test`, `docs`, `chore` (tooling/deps/CI), `style` (formatting only), `revert`. Never `update`/`change`/`modify`/`misc`/`various`.

**Scopes** (lowercase; prefer the most specific):

- Layers: `api` `application` `deploy` `ci`
- Auth/access: `auth` (credentials, JWT, TOTP, Entra exchange) `auth-config` (in-app provider/MFA config) `permissions` (roles, grants, sharing)
- Resources: `dashboards` `pages` (custom HTML pages) `warehouses` (connection CRUD + query-access grants) `data-dict` `bi-connections`
- Features: `portal` `embed` `powerbi` `pipelines` `adf` `notifications` `exports` `features` (flags) `changes` (change ledger) `audit` `users` `roles`
- Infrastructure: `azure` `bicep` `docker` `migrations` `sql-compat` (PostgreSQL / Azure SQL differences)

Omit scope only for genuinely codebase-wide commits (`chore: upgrade Python to 3.12`).

**Breaking changes** — `BREAKING CHANGE:` footer, also flagged in the PR description. Counts as breaking: a backwards-incompatible schema change, a removed or renamed public API endpoint, a changed session token format or auth flow, a renamed or removed env var, a new `EmbedType` or provider key the other layer does not know.

**Examples:**

```
feat(powerbi): refresh the embed token before it expires mid-session

fix(migrations): give every String column an explicit length

Azure SQL rejects VARCHAR without one — SQLAlchemy's mssql dialect raises
CompileError before the statement reaches the server — so the schema could
not be created at all on the deployment target.

feat(api): move audit endpoints from /governance to /audit

BREAKING CHANGE: GET /governance/audit is now GET /audit.
Closes #12
```

Anti-patterns: no type/scope (`updated the connector`), past tense (`fixed auth error`), vague scope (`fix(stuff)`).

On-demand reference: [`@REVIEW.md`](REVIEW.md) (review checklist).
