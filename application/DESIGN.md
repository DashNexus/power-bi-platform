# Application Layer — Design Document

Complete architectural design and implementation status for the Sec Dash frontend.

Tokens, primitives, and UI conventions live in [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) — read that before writing any component.

---

## Table of Contents

1. [Architecture Overview](#1-architecture-overview)
2. [Route Inventory](#2-route-inventory)
3. [Component Inventory](#3-component-inventory)
4. [Data Layer Mapping](#4-data-layer-mapping)
5. [Feature Flag Matrix](#5-feature-flag-matrix)
6. [Authentication Architecture](#6-authentication-architecture)
7. [Embed Architecture](#7-embed-architecture)
8. [Implementation Status](#8-implementation-status)
9. [Testing Plan](#9-testing-plan)
10. [Additional Features](#10-additional-features)

---

## 1. Architecture Overview

### 1.1 Tech stack

| Layer | Technology | Version |
|---|---|---|
| Framework | Next.js (App Router) | 15 |
| Runtime | React Server Components (default) | React 19 |
| Auth | Auth.js v5 | beta.25 |
| Styling | Tailwind CSS v4 + first-party primitives (`components/ui`) | v4 |
| Data Fetching | @tanstack/react-query | 5.56 |
| State Management | React cache (server) + hooks (client) | — |
| Forms | react-hook-form + zod | 7.x / 3.x |
| Charts | Recharts, @xyflow/react | 2.x / 12.x |
| Embed SDKs | powerbi-client-react, @tableau/embedding-api | 1.x / 3.x |
| Editor | Monaco Editor | 0.47+ |
| Variants | class-variance-authority | 0.7 |
| Theming | next-themes (`.dark` class) | 0.4 |
| Testing | Vitest | 2.1+ |

### 1.2 High-level diagram

```
┌──────────────────────────────────────────────────────────┐
│                       Browser                            │
│                                                          │
│  Server Components       Client Components   EventSource │
│  apiFetch<T>()           createClientFetch() (SSE chat)  │
│  session via auth()      token from useSession()         │
└──────────────────────────────────────────────────────────┘
         │                       │                   │
         │       Bearer JWT      │                   │
         ▼                       ▼                   ▼
┌──────────────────────────────────────────────────────────┐
│                FastAPI Backend (:8000)                   │
└──────────────────────────────────────────────────────────┘
         │                       │
         ▼                       ▼ (read-only, marts schema)
┌──────────────┐      ┌──────────────────────────────────┐
│ biplatform   │      │      biplatform_warehouse        │
│ _app         │      │  (marts: dim_* · fct_*)          │
└──────────────┘      └──────────────────────────────────┘
```

### 1.3 Key design decisions

1. **Server Components are default** — `"use client"` only when browser APIs, event handlers, or React hooks are needed
2. **All API calls go through typed wrappers** — `apiFetch<T>()` (server) / `createClientFetch(token)` (client); raw `fetch()` to the backend is forbidden
3. **AI chat uses direct EventSource** — opens to `NEXT_PUBLIC_API_URL/chat`; Next.js API routes buffer responses and break SSE
4. **Feature flags are server-cached** — `isEnabled()` uses React `cache()` for per-request deduplication
5. **Auth config is dual-exported** — `authConfig` (edge-safe, no providers, no network) for middleware; full `auth` for server components
6. **FEATURE_* env vars win over DB** — infrastructure can hard-disable/enable features without touching the database
7. **Colour only ever comes from a semantic token** — `globals.css` maps tokens into Tailwind's `--color-*` namespace via `@theme inline`; raw palette classes (`bg-white`, `text-gray-500`) are forbidden because they cannot follow the theme. See [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md)
8. **Controls come from `components/ui`** — buttons, cards, inputs, tables, badges, and tabs are shared primitives, not per-page class strings
9. **OAuth client secrets come from the environment, never the API** — `GET /admin/auth-config/providers` masks `client_secret` and requires an admin session, so it can neither supply a usable secret nor be read from the login page (`lib/authProviders.ts`)

### 1.4 Directory map

```
application/src/
├── middleware.ts                        # Edge session enforcement + admin redirect
├── app/
│   ├── (auth)/                          # Unauthenticated routes
│   │   ├── layout.tsx
│   │   ├── login/page.tsx               # Credential form + OAuth provider buttons
│   │   └── mfa/page.tsx                 # TOTP + email OTP challenge
│   ├── (platform)/                      # Authenticated routes (session required)
│   │   ├── layout.tsx                   # Session guard + AppShell
│   │   ├── dashboard/page.tsx           # Dashboard listing
│   │   ├── dashboard/[id]/page.tsx      # Embed view
│   │   ├── pages/[slug]/page.tsx        # Custom HTML pages
│   │   ├── chat/page.tsx                # AI chat (EventSource)
│   │   ├── exports/page.tsx             # Export history + schedule manager
│   │   ├── settings/page.tsx
│   │   ├── settings/profile/page.tsx
│   │   ├── settings/security/page.tsx   # TOTP enrollment + active sessions
│   │   └── settings/notifications/page.tsx
│   ├── admin/                           # Admin routes
│   │   ├── layout.tsx                   # Role guard: non-admin → /dashboard
│   │   ├── users/page.tsx
│   │   ├── roles/page.tsx
│   │   ├── roles/[id]/page.tsx          # Permission matrix
│   │   ├── auth-config/page.tsx         # OAuth provider CRUD
│   │   ├── auth-config/mfa/page.tsx     # MFA settings
│   │   ├── features/page.tsx            # Feature flag toggle grid
│   │   ├── org-settings/page.tsx        # Logo, colour, app name
│   │   ├── audit/page.tsx               # Access audit log
│   │   ├── pages/page.tsx
│   │   ├── pages/new/page.tsx
│   │   ├── pages/[id]/page.tsx          # Monaco editor + version history
│   │   ├── pipelines/page.tsx           # Prefect monitor
│   │   ├── lineage/page.tsx             # dbt DAG
│   │   ├── catalog/page.tsx             # Data catalog browser
│   │   ├── governance/page.tsx          # PII tags + audit log
│   │   ├── backups/page.tsx
│   │   ├── retention/page.tsx
│   │   ├── dashboards/                  # (empty — forms not yet built)
│   │   └── streamlit/                   # (empty — admin page not yet built)
│   ├── api/
│   │   ├── auth/[...nextauth]/route.ts  # Auth.js handler
│   │   ├── auth/oauth-exchange/route.ts # First-time OAuth provisioning
│   │   └── streamlit/[appId]/[...path]/ # (empty — reverse proxy not yet built)
│   ├── globals.css
│   ├── layout.tsx                       # Root layout (font, metadata)
│   └── page.tsx                         # Root → redirects to /login
├── components/
│   ├── admin/     AuthProviderCard, DataTable, FeatureToggleGrid, PermissionMatrix
│   ├── auth/      LoginForm, MfaForm
│   ├── backups/   BackupHistoryTable, TriggerBackup
│   ├── chat/      ChatWindow, ChatInput, MessageBubble
│   ├── dashboards/ DashboardCard, DashboardCreator, EmbedFrame, FilterPanel,
│   │               PowerBIEmbed, TableauEmbed
│   ├── exports/   ExportHistoryTable, NewExportDialog, NewScheduleDialog, ScheduleTable
│   ├── governance/ CatalogBrowser, PiiManagement, QualityScores
│   ├── layout/    AppShell, Sidebar, TopBar
│   ├── lineage/   LineageGraph, ModelNode
│   ├── notifications/ NotificationPreferences
│   ├── prefect/   FlowRunTable, DeploymentList
│   ├── retention/ NewPolicyDialog, PolicyTable
│   ├── settings/  TotpEnrollment
│   └── ui/        CommandPalette
├── dashboards/custom/
│   └── manifest.ts                      # Custom React dashboard registry
└── lib/
    ├── api.ts                           # apiFetch<T>(), createClientFetch(token)
    ├── auth.ts                          # authConfig + auth + signIn + signOut
    ├── features.ts                      # FeatureKey, isEnabled(), getAllFeatures(),
    │                                    # keyToEnvVar(), getEnvOverride()
    ├── permissions.ts                   # Role, ROLE_LEVEL, hasRole(), hasAnyRole()
    └── utils.ts                         # cn() (clsx + tailwind-merge)
```

---
## 2. Route Inventory

79 `page.tsx` routes: 4 unauthenticated, 34 platform, 40 admin, plus the root redirect. Generate the current list with:

```bash
cd application/src/app && find . -name page.tsx | sort
```

### 2.1 Unauthenticated routes — `(auth)/`

No session guard; each redirects to `/home` when a session already exists.

| Route | Purpose |
|---|---|
| `/login` | Credential form, inline TOTP step, and a button per configured OAuth provider |
| `/forgot-password` | Requests a reset link; the API responds identically whether or not the address exists |
| `/reset-password` | Consumes the emailed token and sets a new password |
| `/mfa` | Legacy — redirects to `/login`. The TOTP challenge is now a second step inside `LoginForm` |

### 2.2 Platform routes — `(platform)/`

Session enforced by `(platform)/layout.tsx`, which also mounts `AppShell`, resolves feature flags, and injects org theming. Feature-flagged groups are gated again in their own `layout.tsx`.

| Area | Routes | Feature flag |
|---|---|---|
| Home & discovery | `/home`, `/resources` | — |
| Dashboards | `/dashboard`, `/dashboard/[id]` | `dashboards`, `embed.*` |
| AI chat | `/chat` | `chat` |
| Exports | `/exports` | `exports` |
| Custom pages | `/pages`, `/pages/[slug]` | `custom_pages` |
| Streamlit apps | `/streamlit`, `/streamlit/[id]` | `embed.streamlit` |
| ERDs | `/erds`, `/erds/[id]` | `lineage` |
| Data lineage | `/data-lineage`, `/data-lineage/[id]` | `data_lineage` |
| Data dictionary | `/data-dicts`, `/data-dicts/[id]` | `governance` |
| Timelines | `/timelines`, `/timelines/[id]` | `timelines` |
| Pipelines | `/pipelines`, `/pipelines/[id]` | `pipelines` |
| Planning | `/clients`, `/clients/[id]`, `/projects`, `/projects/[id]`, `/gantt/[id]` | `project_planning` |
| Work management | `/project-management`, `/boards`, `/boards/[id]` | `project_management` |
| Time tracking | `/time-tracking` | `time_tracking` |
| Billing | `/billing` | `billing` |
| Settings | `/settings`, `/settings/profile`, `/settings/security`, `/settings/notifications` | — |

**Flag-before-permission:** the org feature flag is checked *before* permissions and per-resource grants. A grant that appears not to work is usually a disabled flag.

### 2.3 Admin routes — `admin/`

`admin/layout.tsx` redirects anyone below `admin` to `/home`.

| Area | Routes |
|---|---|
| Identity | `/admin/users`, `/admin/roles`, `/admin/roles/[id]`, `/admin/auth-config`, `/admin/auth-config/mfa` |
| Platform config | `/admin/features`, `/admin/org-settings`, `/admin/nav-config` |
| Content | `/admin/dashboards`, `/admin/pages`, `/admin/pages/new`, `/admin/pages/[id]`, `/admin/streamlit`, `/admin/timelines`, `/admin/timelines/new`, `/admin/timelines/[id]` |
| Data platform | `/admin/warehouses`, `/admin/bi-connections`, `/admin/data-pipelines`, `/admin/data-dictionary`, `/admin/data-lineage`, `/admin/erd`, `/admin/lineage`, `/admin/catalog` |
| Governance | `/admin/data-governance`, `/admin/governance`, `/admin/audit`, `/admin/changes`, `/admin/retention`, `/admin/backups` |
| Delivery | `/admin/clients`, `/admin/clients/new`, `/admin/clients/[id]`, `/admin/projects`, `/admin/projects/new`, `/admin/projects/[id]`, `/admin/tickets` |
| Ops | `/admin/notifications`, `/admin/notification-groups`, `/admin/billing-connections` |

### 2.4 API routes

| Route | Purpose |
|---|---|
| `/api/auth/[...nextauth]` | Auth.js handler |
| `/api/auth/oauth-exchange` | First-time OAuth user provisioning |

### 2.5 Error and loading boundaries

| File | Covers |
|---|---|
| `app/error.tsx` | Any route render error, with `reset()` and the error digest |
| `app/global-error.tsx` | Root-layout failure; renders its own `<html>` with inline styles |
| `app/not-found.tsx` | 404s, including `notFound()` from a disabled feature |
| `app/(platform)/loading.tsx`, `app/admin/loading.tsx` | Streaming fallbacks |

## 3. Component Inventory

### 3.0 Shared primitives (`components/ui/`)

The layer every feature component builds on. Full reference: [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md).

| Component | Description |
|---|---|
| `Button` / `buttonVariants` | The only button. 7 variants × 5 sizes, `isLoading` spinner |
| `Card` (+ `Header`/`Title`/`Description`/`Content`/`Footer`) | Surface container |
| `Input`, `Textarea`, `Select`, `Label`, `Field`, `FieldError` | Form controls sharing one `controlClasses` shell |
| `Badge`, `StatusBadge`, `statusTone` | Status pills; `statusTone` is the app-wide state → colour mapping |
| `PageHeader`, `SectionHeader` | Title + description + actions; owns the route's single `<h1>` |
| `EmptyState`, `ErrorState` | Placeholders; `description` is mandatory per BRAND.md |
| `Table*` | Table chrome plus the `TableContainer` horizontal scroll |
| `Alert`, `Skeleton`, `Spinner`, `LoadingRows` | Inline feedback and loading affordances |
| `Tabs` | Underlined tab bar with full ARIA keyboard support |
| `Brand`, `APP_NAME` | Sec Dash lockup; falls back to the org logo/name when white-labelled |
| `AccessDenied`, `CommandPalette` | Permission fallback; ⌘K palette |

### 3.1 Admin components (`components/admin/`)

| Component | Description |
|---|---|
| `AuthProviderCard.tsx` | OAuth provider config card (enable toggle, client ID, masked secret, test button) |
| `DataTable.tsx` | Reusable paginated table with sorting and filter inputs |
| `FeatureToggleGrid.tsx` | Feature flag grid with amber `env` badge for env-controlled flags; toggles call API |
| `PermissionMatrix.tsx` | Checkbox grid: rows = permissions, columns = resources; backs the roles editor |

### 3.2 Auth components (`components/auth/`)

| Component | Description |
|---|---|
| `LoginForm.tsx` | Email + password + TOTP code fields; calls `/auth/token` via `signIn("credentials")` |
| `MfaForm.tsx` | TOTP code entry form; used on `/mfa` after password-only sign-in |

### 3.3 Dashboard components (`components/dashboards/`)

| Component | Description |
|---|---|
| `EmbedFrame.tsx` | Base role-checked iframe wrapper; renders nothing if user.role < requiredRole |
| `PowerBIEmbed.tsx` | Wraps `powerbi-client-react`; calls `POST /dashboards/{id}/embed-token` on mount; auto-refreshes before expiry |
| `TableauEmbed.tsx` | Uses `@tableau/embedding-api-latest`; fetches JWT from `POST /dashboards/{id}/tableau-jwt`; passes filters via Tableau JS API |
| `DashboardCard.tsx` | Card UI: thumbnail, name, type badge, data freshness chip |
| `DashboardCreator.tsx` | Embed type picker → type-specific form; submits to `POST /dashboards` |
| `FilterPanel.tsx` | Shared filter controls (dropdowns, date pickers) sourced from `dashboard_filters` |

### 3.4 Chat components (`components/chat/`)

| Component | Description |
|---|---|
| `ChatWindow.tsx` | Main chat UI; opens EventSource directly to FastAPI `/chat`; streams tokens |
| `ChatInput.tsx` | Textarea + submit; sends `?q=` query string to EventSource |
| `MessageBubble.tsx` | Renders a single message (user or AI); AI messages support markdown + table |

### 3.5 Layout components (`components/layout/`)

| Component | Description |
|---|---|
| `AppShell.tsx` | Root layout: sidebar + topbar + main content area |
| `Sidebar.tsx` | Navigation; feature-flag-gated items; role-gated admin section |
| `TopBar.tsx` | User avatar, org name, settings link, sign out |

### 3.6 Lineage components (`components/lineage/`)

| Component | Description |
|---|---|
| `LineageGraph.tsx` | @xyflow/react canvas rendering the dbt model DAG |
| `ModelNode.tsx` | Individual node: model name, materialization badge, freshness indicator |

### 3.7 Governance components (`components/governance/`)

| Component | Description |
|---|---|
| `CatalogBrowser.tsx` | Expandable tree: schemas → tables → columns with descriptions |
| `PiiManagement.tsx` | PII tag matrix; toggle tags per column; calls `POST/DELETE /governance/pii-tags` |
| `QualityScores.tsx` | dbt test result table: model name, pass/warn/fail counts per run |

---

## 4. Data Layer Mapping

All API calls from the application go through one of two wrappers in `lib/api.ts`:

```typescript
// Server component — reads session via auth() server-side
const data = await apiFetch<MyType>('/admin/features')

// Client component — receives token from useSession()
const fetchFn = createClientFetch(session.user.access_token)
const data = await fetchFn<MyType>('/data/my_table?limit=100')
```

**Never** call `fetch()` directly to the backend.

**Exception:** AI chat SSE stream — opens `EventSource` directly to FastAPI:

```typescript
const es = new EventSource(`${process.env.NEXT_PUBLIC_API_URL}/chat?q=${encodeURIComponent(question)}`)
```

### 4.1 Server component data fetching

```typescript
// (platform)/dashboard/page.tsx — server component
export default async function DashboardPage() {
  const dashboards = await apiFetch<Dashboard[]>('/dashboards')
  return <DashboardList dashboards={dashboards} />
}
```

Data is fetched at request time. No client-side loading state for the initial render.

### 4.2 Client component data fetching

```typescript
// components/dashboards/DashboardCard.tsx — client component
'use client'
const { data: session } = useSession({ required: true })
const fetch = createClientFetch(session?.user.access_token)
const { data } = useQuery({
  queryKey: ['freshness', dashboardId],
  queryFn: () => fetch<FreshnessData>(`/data/${tableName}/freshness`),
  refetchInterval: 60_000,
})
```

---

## 5. Feature Flag Matrix

Feature flags gate both sidebar navigation items and the pages themselves. Flags are checked server-side in layouts or page components via `isEnabled()`.

| Feature key | Sidebar item | Gated page(s) |
|---|---|---|
| `chat` | AI Chat | `/chat` |
| `exports` | Data Exports | `/exports` |
| `custom_pages` | Pages (user) | `/pages/[slug]`, `/admin/pages*` |
| `prefect_monitor` | Pipeline Monitor | `/admin/pipelines` |
| `lineage` | Data Lineage | `/admin/lineage` |
| `governance` | Governance | `/admin/catalog`, `/admin/governance` |
| `backups` | Backup & Restore | `/admin/backups` |
| `retention` | Data Retention | `/admin/retention` |
| `embed.powerbi` | Power BI embed type | Dashboard create/edit forms |
| `embed.tableau` | Tableau embed type | Dashboard create/edit forms |
| `embed.custom_react` | Custom React dashboards | Dashboard create/edit forms |
| `embed.streamlit` | Streamlit embed type | `/admin/streamlit`, Streamlit proxy |

### 5.1 Env var override behaviour

Setting `FEATURE_CHAT=false` in the server environment disables the chat page for all organisations on that deployment, regardless of DB configuration. The feature flag admin UI shows an amber "env" badge and a disabled toggle for any env-controlled flag.

---

## 6. Authentication Architecture

### 6.1 Two Auth.js configs

Two exports from `lib/auth.ts` — use the correct one in each context:

```typescript
// authConfig — edge-safe, no providers, no network calls
// Required for middleware.ts (runs on the Edge runtime)
import { authConfig } from '@/lib/auth'

// auth — full config with dynamic OAuth providers
// Use in server components, API routes, and the Auth.js handler
import { auth } from '@/lib/auth'
```

**Critical:** `authConfig` must have a `session` callback that copies custom JWT fields (`role`, `user_id`, `org_id`, `access_token`) to `session.user`. Without this, `req.auth.user.role` is always `undefined` in middleware, and the admin redirect never fires correctly.

### 6.2 Middleware

`middleware.ts` handles two concerns:

1. **Session enforcement** — unauthenticated users are redirected to `/login`
2. **Admin role guard** — users with role ≤ `analyst` requesting `/admin/*` are redirected to `/dashboard`

```typescript
// middleware.ts
import NextAuth from 'next-auth'
import { authConfig } from '@/lib/auth'

const { auth } = NextAuth(authConfig)

export default auth((req) => {
  const role = (req.auth?.user as { role?: string })?.role ?? 'viewer'
  const isAdminRoute = req.nextUrl.pathname.startsWith('/admin')

  if (isAdminRoute && !hasRole(role, 'admin')) {
    return NextResponse.redirect(new URL('/dashboard', req.url))
  }
})
```

### 6.3 OAuth provider loading

The full `auth` config loads enabled OAuth providers from `GET /admin/auth-config/providers` at startup with ISR revalidation (300 seconds). Providers that are disabled in the DB do not appear on the login page.

### 6.4 Role helpers

```typescript
// lib/permissions.ts
const ROLE_LEVEL: Record<string, number> = {
  viewer: 1, analyst: 2, admin: 3, superadmin: 4,
}

export function hasRole(userRole: string, requiredRole: string): boolean {
  return (ROLE_LEVEL[userRole] ?? 0) >= (ROLE_LEVEL[requiredRole] ?? 99)
}
```

---

## 7. Embed Architecture

### 7.1 Power BI

`PowerBIEmbed.tsx` uses `powerbi-client-react`:

1. Calls `POST /dashboards/{id}/embed-token` on mount
2. Renders `<PowerBIEmbed embedConfig={...} />` with the returned token + embed URL
3. Schedules a refresh via `setInterval(refetch, (expiry - Date.now()) - 120_000)`

Embed token is generated by the API using the org's stored Service Principal credentials. Token is cached in Redis.

### 7.2 Tableau

`TableauEmbed.tsx` uses `@tableau/embedding-api-latest`:

1. Calls `POST /dashboards/{id}/tableau-jwt` on mount
2. Renders `<tableau-viz src={viewUrl} token={jwt} />`
3. After viz load event, applies filter values from `dashboard_filters` via `viz.workbook.activeSheet.applyFilterAsync()`

JWT is signed on the API using the org's Connected App RS256 private key. TTL is 15 minutes; component refetches before expiry.

### 7.3 Streamlit

Streamlit apps are never directly accessible. The Next.js route `app/api/streamlit/[appId]/[...path]/route.ts` reverse-proxies all requests to `localhost:{port}`. The proxy validates the session before forwarding.

`StreamlitEmbed.tsx` renders an iframe to `/api/streamlit/{appId}/`.

### 7.4 Custom React dashboards

Developers place `.tsx` files in `src/dashboards/custom/` and register them in `manifest.ts`:

```typescript
// src/dashboards/custom/manifest.ts
export const DASHBOARDS: Record<string, DashboardManifestEntry> = {
  'sales-overview': {
    label: 'Sales Overview',
    component: lazy(() => import('./SalesOverview')),
  },
}
```

`CustomReactDash.tsx` dynamically imports the component by key from the manifest and passes `{user, filters, parameters}` props.

---

## 8. Implementation Status

### 8.1 Auth and layout

| Area | Status | Notes |
|---|---|---|
| Login page + credential form | ✅ Complete | Primitives-based; inline TOTP step |
| MFA challenge | ✅ Complete | Second step inside `LoginForm`. The old `/mfa` page passed the plaintext password through `sessionStorage`; it now never leaves component state |
| OAuth provider buttons | ✅ Complete | Driven by `lib/authProviders.ts` from env vars. Previously a stub returning `[]`, so no button ever rendered — and `lib/auth.ts` registered no provider either, because it fetched an admin-only endpoint unauthenticated |
| Design tokens + UI primitives | ✅ Complete | `@theme inline` in `globals.css`; `components/ui`. See [DESIGN_SYSTEM.md](DESIGN_SYSTEM.md) |
| Dark mode | ✅ Complete | Token-driven. 1,640 of 1,992 colour utilities previously had no `dark:` partner |
| Error / loading / 404 boundaries | ✅ Complete | `error.tsx`, `global-error.tsx`, `not-found.tsx`, two `loading.tsx` |
| Auth.js session callback bug fix | ✅ Complete | `authConfig` session callback copies `role` to `req.auth.user` |
| App shell (sidebar + topbar) | ✅ Complete | |
| Middleware (session + admin guard) | ✅ Complete | |
| `lib/auth.ts` | ✅ Complete | Both configs; session callback |
| `lib/api.ts` | ✅ Complete | `apiFetch`, `createClientFetch` |
| `lib/permissions.ts` | ✅ Complete | Role hierarchy |
| `lib/features.ts` | ✅ Complete | `isEnabled`, `getAllFeatures`, `keyToEnvVar`, `getEnvOverride` |

### 8.2 Admin pages

| Page | Status | Notes |
|---|---|---|
| `/admin/users` | ✅ Complete | Invite, CRUD, role picker |
| `/admin/roles` | ✅ Complete | Permission matrix |
| `/admin/auth-config` | ✅ Complete | Provider cards, test button |
| `/admin/auth-config/mfa` | ✅ Complete | TOTP required, grace period |
| `/admin/features` | ✅ Complete | Toggle grid, env badge, env override |
| `/admin/org-settings` | ✅ Complete | Logo, colour, app name |
| `/admin/audit` | ✅ Complete | Access log table |
| `/admin/pages` | ✅ Complete | List + CRUD |
| `/admin/pages/[id]` | ✅ Complete | Monaco editor + version history |
| `/admin/pipelines` | ✅ Complete | Flow run table + deployment list + manual trigger |
| `/admin/lineage` | ✅ Complete | @xyflow/react DAG |
| `/admin/catalog` | ✅ Complete | Table/column browser |
| `/admin/governance` | ✅ Complete | PII tags + quality scores |
| `/admin/backups` | ✅ Complete | History table + manual trigger |
| `/admin/retention` | ✅ Complete | Policy list + dry-run + apply |
| `/admin/dashboards` | 🔲 Not started | Forms for Power BI / Tableau / Streamlit / custom React |
| `/admin/streamlit` | 🔲 Not started | App list + upload form + status badges |

### 8.3 Platform pages

| Page | Status | Notes |
|---|---|---|
| `/dashboard` | ✅ Complete | Listing with DashboardCard |
| `/dashboard/[id]` | 🚧 In progress | EmbedFrame done; embed type dispatching partial |
| `/chat` | 🚧 In progress | ChatWindow + EventSource wired; history partial |
| `/exports` | 🚧 In progress | History table done; schedule manager partial |
| `/pages/[slug]` | ✅ Complete | Renders HTML from API |
| `/settings/*` | 🚧 In progress | Profile done; TOTP enrollment partial; notifications partial |

### 8.4 API routes

| Route | Status |
|---|---|
| `/api/auth/[...nextauth]` | ✅ Complete |
| `/api/auth/oauth-exchange` | ✅ Complete |
| `/api/streamlit/[appId]/[...path]` | 🔲 Not started |

---

## 9. Testing Plan

### 9.1 Test runner

Vitest with `vite-tsconfig-paths` for path alias resolution. Environment: `node` (no browser required for unit tests).

```bash
cd application
npm run test         # run once (vitest run)
npm run test:watch   # watch mode (vitest)
```

Per-file environment: unit tests default to `node`; component tests opt in with a
`// @vitest-environment jsdom` pragma on line 1.

### 9.2 Test file locations

135 tests across 13 files. Mirror the source tree under `__tests__/`.

```
application/src/
├── __tests__/setup.ts                        # Mocks: react cache, @/lib/api
├── middleware.test.ts                        # admin guard + MFA-enrolment guard
├── lib/__tests__/
│   ├── api.test.ts                           # apiFetch error handling, token injection
│   ├── authProviders.test.ts                 # OAuth discovery; button list == registered list
│   ├── features.test.ts                      # env override precedence over DB
│   ├── navAccess.test.ts                     # per-resource nav filtering
│   └── permissions.test.ts                   # role hierarchy
└── components/
    ├── admin/__tests__/                      # DataTable, FeatureToggleGrid
    ├── ai/__tests__/                         # AiAssistProvider, ChangeHistory, useAiStream
    ├── auth/__tests__/LoginForm.test.tsx     # validation, TOTP step, OAuth buttons, no stored password
    └── ui/__tests__/Badge.test.tsx           # statusTone vocabulary
```

**Mock `fetch` in any test that renders `LoginForm`.** It pre-checks credentials
against the API before calling `signIn()`; leaving `fetch` real made the suite
depend on a backend at `localhost:8000` and was the cause of four silent failures.

### 9.3 Existing test coverage

`features.test.ts` — 17 tests across 4 describe blocks:

| Block | Tests | Verifies |
|---|---|---|
| `keyToEnvVar` | 2 | Simple keys and dotted keys (e.g. `embed.powerbi` → `FEATURE_EMBED_POWERBI`) |
| `getEnvOverride` | 8 | Null when unset, null on empty string, `true`/`false`/`"1"`/`"yes"` handling |
| `isEnabled` | 5 | Env override short-circuits API call; false env wins over true DB; API value used when no env; missing key = false; API error = false |
| `getAllFeatures` | 2 | Merges API values; env override wins per key |

### 9.4 Planned test files

```
src/lib/__tests__/
├── permissions.test.ts     # hasRole, hasAnyRole — role hierarchy checks
└── api.test.ts             # apiFetch error handling, token injection

src/components/admin/__tests__/
├── FeatureToggleGrid.test.tsx   # Env badge renders; toggle disabled when env-controlled
└── DataTable.test.tsx           # Sorting, pagination, filter

src/components/auth/__tests__/
└── LoginForm.test.tsx           # Form submission, error states

src/middleware.test.ts           # Admin redirect fires for viewer; passes for admin
```

### 9.5 Vitest configuration

```typescript
// vitest.config.ts
import { defineConfig } from 'vitest/config'
import tsconfigPaths from 'vite-tsconfig-paths'

export default defineConfig({
  plugins: [tsconfigPaths()],
  test: {
    environment: 'node',
    globals: true,
    include: ['src/**/*.test.ts', 'src/**/*.test.tsx'],
    setupFiles: ['src/__tests__/setup.ts'],
  },
})
```

### 9.6 Test patterns

```typescript
// Pattern: isolate env var state across tests
beforeEach(() => {
  vi.resetModules()
  delete process.env.FEATURE_CHAT
})

// Pattern: re-import module after env change
async function importFeatures() {
  vi.resetModules()
  return import('@/lib/features')
}

// Pattern: mock API with specific return value
const { apiFetch } = await import('@/lib/api')
vi.mocked(apiFetch).mockResolvedValue([
  { feature_key: 'chat', enabled: true, env_override: false },
])
```

---

## 10. Additional Features

### 10.1 Dashboard create/edit forms (immediate priority)

Complete the empty `admin/dashboards/` directory with:
- `new/page.tsx` — embed type picker (Power BI / Tableau / Streamlit / Custom React)
- `[id]/page.tsx` — type-specific config form + permissions tab + filters tab

Each embed type renders a different form section. Power BI shows workspace → report selectors (populated from `GET /embed/powerbi/workspaces`). Tableau shows workbook → view selectors with thumbnail previews.

### 10.2 Streamlit admin page

`admin/streamlit/page.tsx` — app list with status badges (running / stopped / error), file upload form (`.py` + optional `requirements.txt`), and start/stop/restart/delete actions.

`app/api/streamlit/[appId]/[...path]/route.ts` — reverse proxy via `fetch()` with session guard. Required for Streamlit embeds to work.

### 10.3 Data freshness badges on dashboard cards

Each `DashboardCard` shows "Updated X minutes ago" by polling `GET /data/{tableName}/freshness`. Stale data (> SLA hours) shows an amber warning chip.

### 10.4 Global command palette

`⌘K` opens `CommandPalette.tsx` which calls `GET /search?q=`. Results include dashboards, pages, catalog entries, and users. Useful for large deployments with many dashboards. The component skeleton already exists in `components/ui/CommandPalette.tsx`.

### 10.5 Real-time pipeline status

The pipelines page currently shows historical flow run data. Add a WebSocket or SSE subscription to Prefect's flow run events endpoint to push status updates in real time — no manual page refresh needed when a pipeline finishes.

### 10.6 Dark mode

Tailwind v4 supports CSS variables for theming. Add `class="dark"` toggle on the root element and define dark-mode overrides in `globals.css`. Persist preference to `localStorage`; respect `prefers-color-scheme` on first visit.

### 10.7 Sentry integration

Add `@sentry/nextjs` for client-side and server-side error reporting. Configure in `next.config.ts` using `withSentryConfig()`. `NEXT_PUBLIC_SENTRY_DSN` is already documented in `.env.example`.

### 10.8 Session expiry warning

Show a toast notification 5 minutes before the JWT access token expires (derived from the JWT `exp` claim stored in the session). Prompt the user to re-authenticate or auto-refresh the token via `POST /auth/refresh` if they are active.
