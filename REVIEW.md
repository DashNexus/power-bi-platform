# BI Platform — Code Review Standards

Standards for reviewing pull requests across all layers of the BI Platform.
Load this file with `@REVIEW.md` when performing a code review.

---

## 1. What a Review Covers

Every pull request review addresses the following in order of priority:

| Priority | Category | Examples |
|---|---|---|
| 🔴 Blocking | Correctness | Wrong logic, data loss, broken contract |
| 🔴 Blocking | Security | Hardcoded credentials, SQL injection, PII leak |
| 🔴 Blocking | Data integrity | Broken watermarks, missing advisory lock, upsert key wrong |
| 🟡 Advisory | Performance | Missing batch size limit, full table scan in AI query |
| 🟡 Advisory | Observability | Missing pipeline run log entry, swallowed exception |
| 🟡 Advisory | Test coverage | Untested error path, no integration test for new loader |
| 🟢 Nitpick | Style | Naming, docstring format, comment wording |
| 🟢 Nitpick | Simplification | Unnecessarily complex implementation of something simple |

**Blocking findings** must be resolved before merge.
**Advisory findings** are strong recommendations — the author should either address them or leave an explicit comment explaining why they disagree.
**Nitpicks** are optional. Prefix with `nit:` so the author can triage quickly.

## 2. Review Checklist

Run through these for every PR. Skip sections that are not touched by the diff.

#### General
- [ ] The PR does one logical thing — it is not a mix of features, refactors, and fixes
- [ ] The PR description explains *why*, not just *what*
- [ ] No commented-out code
- [ ] No `# TODO` or `# FIXME` without a linked GitHub issue
- [ ] No hardcoded credentials, tokens, or internal URLs

#### Python
- [ ] All public functions have type annotations and Google-style docstrings
- [ ] Exceptions are caught specifically and re-raised with `from exc`
- [ ] No bare `except:` or silent `except Exception: pass`
- [ ] Imports are ordered (ruff `I` will catch this, but verify ruff ran)
- [ ] `ruff check` and `ruff format --check` pass with no suppressions

#### TypeScript / React
- [ ] Server Components are default; `"use client"` only where genuinely needed
- [ ] No default exports — named exports only
- [ ] Props interfaces defined above the component, not inline
- [ ] `apiFetch()` used for all API calls — no raw `fetch()` to the backend

#### Database portability (PostgreSQL **and** Azure SQL)
- [ ] Every new `String` column has an explicit length — Azure SQL rejects VARCHAR without one
- [ ] A new foreign key does not create a second `ON DELETE CASCADE` path to the same table
      (`tests/test_schema_portability.py` fails if it does; see `services/principal_cleanup.py`)
- [ ] Raw SQL avoids `RETURNING`, `ON CONFLICT`, `NOW()`, `LIMIT`/`OFFSET`, and `pg_*` catalogs
      — the portable spelling lives in `app/sql_compat.py`
- [ ] A path that deletes a user or a role calls `principal_cleanup` first

#### API-specific
- [ ] No cloud SDK imports outside `storage.py` and `secrets.py`
- [ ] Warehouse DB session uses `get_warehouse_db` (read-only) — not `get_app_db`
- [ ] TOTP secrets and provider client secrets stored encrypted with Fernet — never plaintext
- [ ] New router registered in `main.py` with correct prefix and tags
- [ ] New DB tables have an Alembic migration
- [ ] Notification events dispatched through `dispatcher.dispatch_event()` — not inline
- [ ] Role guard uses `require_role()` as a `Depends()` dependency — not a decorator
- [ ] All `/data/*` routes go through `data_query.py` which enforces `WHERE org_id = :org_id`
- [ ] A create/update/delete of a ledger-tracked resource calls `change_ledger.log_*` before commit

#### Application-specific (Next.js 15 / Auth.js v5)
- [ ] `middleware.ts` uses `authConfig` (no providers, no network) — never `auth` from full Auth.js config
- [ ] `params` in page components awaited — `const { id } = await params` (Next.js 15 requirement)
- [ ] New feature pages gated with `isEnabled(key)` from `lib/features.ts`
- [ ] `apiFetch()` used in server components; `createClientFetch(token)` in client components — no raw `fetch()` to backend
- [ ] Dashboard embed tokens fetched at runtime from the API — not hardcoded or stored client-side beyond render
- [ ] A new `EmbedType` value exists in **both** `types/embed.ts` and `api/app/schemas/dashboard.py`
- [ ] `"use client"` only when browser APIs, event handlers, or React hooks are genuinely needed
- [ ] Named exports only — no `export default` on components
- [ ] Props interfaces named `<ComponentName>Props` and defined above the component

#### Security
- [ ] No credentials, tokens, or PII in logs or error messages
- [ ] Webhook URLs and phone numbers redacted before they reach the delivery history
- [ ] JWT validation present on all non-`/auth/*` and non-`/health` routes
- [ ] Role guard applied to admin routes

#### Tests
- [ ] New public functions have unit tests
- [ ] Error paths are tested (not just the happy path)
- [ ] Integration tests marked `@pytest.mark.integration`
- [ ] No real credentials or production URLs in test fixtures

## 3. How to Give Feedback

**Label every comment** so authors know what action to take:

| Label | Meaning | Author action |
|---|---|---|
| `blocking:` | Must be fixed before merge | Fix or push back with justification |
| `advisory:` | Strong recommendation | Address or comment why not |
| `nit:` | Minor style or simplification | Take or leave — no reply needed |
| `question:` | Asking for understanding, not requesting change | Answer in a comment |
| `praise:` | Something done particularly well | No action needed |

**Be specific and constructive:**

```
# ✅ Specific, actionable, explains why
blocking: `_verify_key` compares hashes with `==` instead of
`hmac.compare_digest`. This is vulnerable to timing attacks. Use
`hmac.compare_digest(computed, received)` instead.

# ❌ Vague and discouraging
this is wrong, fix the validation
```

**Suggest, don't rewrite:**

Offer a specific alternative when the problem has an obvious fix; otherwise
describe the constraint and let the author find the solution:

```
# ✅
advisory: Consider using `tenacity.retry` here instead of a manual loop —
it gives you exponential backoff and jitter without the boilerplate.

# ❌ (reviewer rewrites the author's code unprompted)
```

**Acknowledge trade-offs:** If a choice has a legitimate downside the author
probably considered, say so — it shows you understand the context.

## 4. Response Expectations

| Role | Expectation |
|---|---|
| Reviewer | First review within **1 business day** of PR opening |
| Author | Address or respond to all comments within **1 business day** of review |
| Re-review | Within **4 hours** of author marking "ready for re-review" |
| Merge | Author merges after all blocking comments resolved and 1 approval |

A PR open for more than **3 business days** without activity should be
flagged in the team channel.
