# Application Layer — Claude Code Guide

Next.js 15 App Router (TypeScript, Tailwind v4 + first-party primitives).
Auth.js v5 — Credentials plus **Microsoft Entra ID only**, with TOTP MFA.
Dashboards, custom pages, data dictionary, pipeline monitoring, exports, and the
admin console.

## UI: tokens and primitives — read `@DESIGN_SYSTEM.md` before writing components

Two rules cover most of it:

- **Never write a raw palette class.** No `bg-white`, `text-gray-500`,
  `bg-blue-600`, `border-gray-200` — use the semantic token (`bg-card`,
  `text-muted-foreground`, `bg-primary`, `border-border`). Tokens are already
  theme-aware, so **never add a `dark:` variant to one**.
- **Never hand-roll a control.** `Button`, `Card`, `Input`/`Field`/`Select`,
  `Badge`/`StatusBadge`, `Table*`, `Tabs`, `PageHeader`, `EmptyState`, `Alert`,
  `Skeleton`, and `Brand` all come from `@/components/ui`. A control that sets
  only borders and padding is not unstyled, it is **UA white** — which is how
  dozens of hand-rolled `<select>`s came to render white on dark cards.

Tokens live in `src/app/globals.css`. Two things there are load-bearing:

- The `@theme inline` block is what makes the tokens exist: Tailwind v4 derives
  utilities from the `--color-*` namespace, so removing it silently deletes every
  `bg-card` / `text-muted-foreground` class in the app.
- `color-scheme: light` / `dark` themes the surfaces the **browser** owns and CSS
  cannot reach — the `<select>` option popup, native scrollbars, form-control
  defaults. Removing it makes every open dropdown white in dark mode regardless
  of how the control is styled.

## Structure

```
application/src/
├── app/
│   ├── (auth)/          login, mfa, password reset — unauthenticated
│   ├── (platform)/      session guard in layout.tsx; home/, dashboard/, pages/,
│   │                    data-dicts/, pipelines/, exports/, resources/, settings/
│   ├── admin/           layout.tsx redirects non-admins; users, roles, auth-config,
│   │                    dashboards, pages, bi-connections, warehouses, nav-config,
│   │                    data-dictionary, data-pipelines, notification-groups,
│   │                    audit, changes
│   └── api/auth/        Auth.js handler + first-login OAuth provisioning
├── components/          one dir per feature (admin, auth, changes, dashboards,
│                        exports, layout, notifications, pipelines, portal,
│                        settings, ui)
├── types/embed.ts       EmbedType — must match the API's Literal
└── lib/
    ├── auth.ts          authConfig (edge-safe) + auth (full, dynamic providers)
    ├── authProviders.ts the single source for which SSO providers exist
    ├── api.ts           apiFetch<T>() (server) + createClientFetch(token) (client)
    ├── features.ts      isEnabled(key) — React cache, server-side per request
    ├── navAccess.ts     isHrefAccessible() — mirrors the server-side route guards
    └── permissions.ts   hasRole(), hasAnyRole() via ROLE_LEVEL
```

## API calls — never raw `fetch()`

```typescript
// Server component — reads the session via auth() internally
const data = await apiFetch<MyType>('/data/tables/orders?limit=100')

// Client component
const { data: session } = useSession({ required: true })
const fetch = createClientFetch(session?.user.access_token)
useQuery({ queryKey: ['orders'], queryFn: () => fetch('/data/tables/orders') })
```

The avatar upload is the one exception: it posts raw `fetch` with `FormData`,
because `createClientFetch` sets a JSON content type.

## Authentication

Two exports from `lib/auth.ts` — pick by context:

- `authConfig` — no providers, no network calls; **middleware only** (Edge-safe)
- `auth` — full config with the Entra provider; server components and API routes

Server: `const session = await auth(); if (!session) redirect('/login')`.
Client: `useSession({ required: true })`. Role checks:
`hasRole(session.user.role, 'admin')` from `lib/permissions.ts`.

- **Microsoft Entra ID is the only SSO provider.** `lib/authProviders.ts` is the
  single source for both the Auth.js registration and the login page's buttons,
  so a provider can never appear as a button without being wired up. A
  deployment ships with `AZURE_AD_*` unset, which leaves password sign-in as the
  only route — that is the intended placeholder state, not a bug.
- **Provider config comes from env vars, not the API.** The API's
  `GET /admin/auth-config/providers` masks `client_secret` and needs an admin
  session, so it can supply neither a usable secret nor anything the
  unauthenticated login page can read.
- **The TOTP challenge is a second step inside `LoginForm`**, not a separate
  route, so the password never leaves component state. `/mfa` redirects to
  `/login`. Any test that renders `LoginForm` must mock `fetch` — it pre-checks
  credentials against the API before calling `signIn()`.
- **`NEXTAUTH_SECRET` must match the API's.** The API verifies the JWT Auth.js
  signed; a mismatch reads as "login works, then every call 401s".

## Next.js 15 gotcha

Page `params` is a **`Promise`** — `const { id } = await params`. The Next.js 14
non-Promise pattern breaks.

## Feature flags

Gate every feature page **server-side at the layout or page level**, not just in
the sidebar: `if (!features['governance']) return <AccessDenied … />`. The
effective flags come from `getAllFeatures()`, which the API computes from the org
flag *and* the user's permissions and grants.

## Dashboard embedding

`EmbedFrame` (`components/dashboards/`) is the base for all iframe embeds.
`PowerBIEmbed` wraps it with token handling (`POST /dashboards/{id}/embed-token`,
auto-refresh).

- **There are two embed types: `powerbi` and `page`.** `types/embed.ts` must stay
  in step with the `EmbedType` Literal in `api/app/schemas/dashboard.py` — the
  API 422s anything else. A `page` embed is an ordinary URL in an iframe, with no
  BI connection behind it, and it is also the fallback for anything unmapped.
- **A pasted share link is not an embed URL.** `publicEmbedUrl.ts` converts one;
  `DashboardEmbedClient` calls it at *render* time, not at save time, so
  dashboards saved with a raw share link start working without being re-entered.
  Verify a change here with `curl -D -`: the embed URL must return `200`, not a
  redirect.
- **`powerbi-client` accesses `self`/`window` at module evaluation time.** Static
  imports evaluate during SSR even inside a `'use client'` file, so `PowerBIEmbed`
  is loaded through `next/dynamic` with `ssr: false`.
- **A vertical scrollbar must never provoke a horizontal one.** Both shells'
  `<main>` carry `[scrollbar-gutter:stable]`, so the gutter is reserved whether
  or not the scrollbar shows. Without it, content growing tall enough to scroll
  narrows the viewport by the scrollbar's width, and a fixed-size embed that had
  just fit becomes ~10px too wide.
- **The embed container is the fullscreen target**, because a dashboard authored
  wider than the viewport can only ever be panned otherwise.
  `.embed-surface:fullscreen` restores `--background`: fullscreen composites
  against black, so a deliberately transparent surface would show through.
- **An embed's background can only be half-controlled.** `.embed-surface` stops
  the app painting behind the frame, but the embed is a cross-origin document —
  its own background and inner scrollbars are unreachable from our CSS.

## Navigation

`PortalNav` (top, everyone) and `Sidebar` (left, admins). The sidebar renders a
static link list gated by feature flags. The top nav does too **until an admin
saves a navigation on `/admin/nav-config`**, after which those items replace the
defaults entirely — configuring a nav must be able to make it shorter, not only
longer.

- **Every configured link goes through `navAccess.isHrefAccessible`.** An admin
  can name any dashboard; the nav shows it only to people who could already open
  it. It covers admin routes, feature-gated sections, and the two deep-link
  shapes (`/dashboard/{id}`, `/pages/{slug}`). A dropdown whose every child is
  hidden is dropped rather than rendered as a menu that opens onto nothing.
- **The platform layout only fetches `getAccessibleResources()` when a custom
  nav exists.** It is several listing calls, and the default nav has no deep
  links to filter.
- **`navConfig` renders after mount, not during SSR.** Radix's `DropdownMenu`
  generates ids with `useId()`, which can differ between the server pass and the
  first client pass when the tree is shaped conditionally; rendering the
  defaults on both makes them match.
- **`/admin/nav-config` validates before saving, and the API validates again.**
  `hrefProblem()` mirrors `_validate_href` in `api/app/schemas/nav_config.py` so
  a mistake is reported next to the field that caused it — the API is still the
  authority, and it is what stops a `javascript:` href.

`Sidebar.tsx` scrolls the **item list**, not the `<nav>`. The collapse toggle is
a `shrink-0` sibling *below* that scroll area, so it stays pinned to the bottom;
scrolling the whole nav pushed the toggle out of reach as soon as the admin list
outgrew the viewport. The scrolling div needs `min-h-0` for `flex-1` to shrink.

## Change history

`components/changes/` — `StatePreview` renders a ledger entry's before/after
snapshots side by side, and `/admin/changes` lists entries with a Revert action
against `GET /changes` and `POST /changes/{id}/revert`. `types.ts` mirrors the
API's `ChangeRecord`.

- **The resource-type filter is fetched from `GET /changes/resource-types`**,
  which serves it from `services/mutation_registry.py`. It used to be a list
  written out in the page, and it had drifted to offer projects, tasks, tickets
  and ERDs — none of which exist in this build — while omitting every type that
  does, so filtering by a real type was impossible. Do not re-inline it; a
  failed fetch degrades to "All types" rather than a toast, because a filter
  menu is not worth interrupting the feed for.
- **Report changes appear here.** Reports are ledger-tracked, but scoped to
  their author: an admin sees that a report changed and can revert only their
  own, matching what `/exports` itself allows.

## Pipeline notifications

`components/pipelines/` — the notification config for a pipeline connection,
reached from `/pipelines/[id]` → Notifications (admin only). `notificationTypes.ts`
is the shared vocabulary every piece imports.

| File | Owns |
|---|---|
| `PipelineNotificationsTab.tsx` | Loading, saving, dirty state, section switch |
| `PipelineOverridesSection.tsx` | Per-pipeline overrides, searchable (an ADF connection can expose hundreds) |
| `ConditionChecksSection.tsx` | Idle + freshness checks, with the create/edit modal |
| `DeliveryHistory.tsx` | The audit trail, expandable to per-destination outcomes |
| `MessageTemplateEditor.tsx` | Template editing with click-to-insert placeholders and a server-rendered preview |
| `NotificationGroupPicker.tsx`, `TestSendDialog.tsx` | Recipient selection; test sends |

- **Settings are staged, not live** — edits mutate local state and apply on Save.
  `savedRef` holds the last server response for the dirty check and Discard; a
  `beforeunload` guard covers full page unloads (the App Router cannot block
  in-app navigation).
- **Preview and test both hit the server**, so what you see is what the poller
  would send, including per-pipeline overrides.
- The UI must keep showing that **failures bypass quiet hours by default** —
  that default is the safe one.

## Exports and reports

`components/exports/` — `ReportDialog` (create *and* edit, one form),
`ReportPreviewPanel` (the Test result), `ReportsTable` (run, edit, delete,
expand for history), `RunHistory`, `ExportHistoryTable` (the global run log),
and `RunFilters` (shared by both run logs). `types.ts` mirrors the API's
`ExportScheduleResponse` and `ExportJobResponse`.

The page has two tabs. A third, Schedules, was removed: it created rows with a
name, a cron and a delivery target but nothing saying what to export, so nothing
could run one. A report with a cron is that feature with the missing half.

- **Running is asynchronous.** `POST /exports/reports/{id}/run` returns a
  *pending* job; the worker executes it within 30 seconds. The tables poll only
  while a run is in flight and stop as soon as one is not, so a settled page
  makes no requests.
- **A report with no cron runs on demand only.** The dialog sends
  `cron_expression: null` when the schedule toggle is off, and the API treats an
  empty string the same way. This is why `update_report` assigns the field
  unconditionally — "only set what was provided" would make a schedule
  impossible to remove.
- **Downloading cannot be a link.** The API is a separate origin behind Bearer
  auth and `download_url` is an fsspec path (`az://…`), which a browser cannot
  fetch. `downloadRun()` in `types.ts` fetches `/exports/jobs/{id}/content` with
  the token and hands the blob over as an object URL.
- **The operations-database option is admin-only** and hidden otherwise; the API
  enforces it regardless. The warning shown when it is selected is not
  decoration — that query is not scoped to the user's organisation.
- **Test and Save send the same body.** `buildBody()` in `ReportDialog` is
  shared by both; a Test that passed while Save sent something slightly
  different would be worse than no Test at all. Testing needs less than saving
  (`canTest` wants a query and a source, not a name or a delivery target).
- **Run-log filtering is a request, not an array filter.** `runFilterParams()`
  builds the query string and the API does the narrowing, because both logs are
  capped by a limit — filtering the rows already fetched would report "no
  matches" for a run sitting just past it. `RunFilters` is shared so the Run
  History tab and the per-report panel behave identically.
- **The filter controls stay mounted through the empty state.** A search that
  matches nothing must not remove the box used to undo it; both tables render
  `RunFilters` above the loading, empty and populated states alike.
- **Email delivery is a disabled option, not a hidden one** — "coming soon"
  reads as *not yet*, where absence reads as *not planned*. The API refuses it
  too, so the two cannot drift.

## Portal listing pages

Every resource listing (`/resources`, `/dashboard`, `/pages`, `/data-dicts`) is
searchable and switches between card and list view.
`components/portal/ResourceBrowser.tsx` renders **both views from one
`ResourceItem`**, so they cannot drift. The view preference persists per page via
`useViewMode.ts`, which reads `localStorage` in an effect and never in initial
state — reading during render hydrate-mismatches, since the server has no
`localStorage`.

## Users, avatars, and the profile page

`components/ui/Avatar.tsx` is the one way a person is rendered.

- **The fallback colour is hashed from the email**, not the name or a list index.
  A colour that changes when a list reorders defeats the only job an initials
  avatar has. `userInitials` falls through name → email local part → `?`, because
  an invited user who never signed in has only an email.
- **`unoptimized` on the `next/image`** — avatars are served from the API origin,
  which is not in `next.config`'s image domains and would 400 through the
  optimiser.
- **The avatar lives in the session JWT**, so the profile page calls
  `useSession().update({ avatar_url })` after an upload or removal. The jwt
  callback checks `'avatar_url' in payload` rather than truthiness — removal
  sends `null`.
- **People-pickers use `GET /users/directory`**, which any authenticated user may
  read. `/admin/users` is admin-only and 403s.
- **A user has no staffing profile** — no user type, capacity, bill rate,
  skills, or department. `UsersClient` rendered inputs for all five; the API had
  columns for none of them but `department`, so four saved nothing at all.
- **An invitation is a link first and an email second.** `POST
  /admin/users/invite` returns `invite_url`, and the dialog switches to showing
  it rather than closing on a toast — an admin whose SMTP is unconfigured has
  nothing else to hand over. The invitations table repeats Copy link, plus
  Resend (which replaces the token, so the row must be swapped for the
  response) and Revoke.
- **`/accept-invite` is in the `(auth)` group and excluded from the middleware
  matcher**, because the invitee has no session. It fetches `GET
  /invites/{token}` before rendering the form: someone holding a used or expired
  link is told so, rather than filling in a password to be refused on submit.

## Adding an admin page

`app/admin/x/page.tsx` → gate with the feature flag if there is one → the admin
layout already handles the role redirect → fetch via `apiFetch()` → add a link in
`components/layout/Sidebar.tsx`.

Every admin page follows the same shape — copy an existing one rather than
inventing a layout:

```tsx
<div className="max-w-5xl space-y-6">
  <PageHeader title="…" description="…" actions={<Button>…</Button>} />
  {loading ? <Card className="p-6"><LoadingRows /></Card>
   : rows.length === 0 ? <Card className="p-6"><EmptyState … /></Card>
   : <Card className="overflow-hidden"><TableContainer><Table>…</Table></TableContainer></Card>}
</div>
```

**External-system connection pages** (BI connections, data pipelines) use
`ProviderConnectionForm` from `components/admin/`, which is driven by the API's
`ProviderMeta.fields` — so a new backend provider appears in the UI with no
frontend change.

## Run locally

```bash
cd application && npm install
cp ../.env.example .env.local   # NEXTAUTH_SECRET, NEXT_PUBLIC_API_URL
npm run dev                     # localhost:3000
```

`NEXT_PUBLIC_API_URL` is inlined into the browser bundle at **build** time, so a
container image is bound to the environment it was built for.

## Read first

`DESIGN_SYSTEM.md`, `src/app/globals.css`, `components/ui/index.ts`,
`lib/auth.ts`, `lib/authProviders.ts`, `lib/api.ts`, `lib/features.ts`,
`lib/permissions.ts`, `middleware.ts`, `types/embed.ts`,
`components/dashboards/EmbedFrame.tsx`
