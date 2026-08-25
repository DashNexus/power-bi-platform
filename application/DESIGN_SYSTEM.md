# Application Layer — Design System

Tokens and primitives every Sec Dash screen is built from. Load this file when writing or reviewing UI in `application/`.

---

## Rules

1. **Never write a raw palette class.** No `bg-white`, `text-gray-500`, `bg-blue-600`, `border-gray-200`. Use the semantic token — it is the only thing that resolves correctly in both themes and under per-org theming.
2. **Never hand-roll a control.** Buttons, cards, inputs, badges, tables, tabs, and empty states come from `@/components/ui`. A one-off `<button className="...">` is a bug, not a shortcut.
3. **No `dark:` variant on a token.** Tokens are already theme-aware; `dark:bg-card` is redundant and drifts. `dark:` is only for the rare case where a *non-token* value must differ per theme.
4. **One `<h1>` per route**, via `<PageHeader>`.
5. **Every empty state answers three questions** — what is empty, why, what next (see [BRAND.md](../BRAND.md) §4).
6. **A control with no `bg-*` is not neutral — it is UA white.** Rule 2 exists partly because of this: dozens of hand-rolled `<select>`/`<input>` elements set only borders and padding, so they rendered white on dark cards. If a shared class-string alias is genuinely warranted, it must name `bg-card text-foreground` explicitly.

`globals.css` sets **`color-scheme: light`/`dark`** alongside the tokens. That is what themes the surfaces the browser owns and CSS cannot reach — the `<select>` option popup, native scrollbars, and form-control defaults. Removing it turns every open dropdown white again. `select`/`option`/`optgroup` additionally get the tokens by element selector, so the popup matches the card it drops out of rather than the browser's generic grey.

## Tokens

Defined in [src/app/globals.css](src/app/globals.css). The `@theme inline` block maps each variable into Tailwind's `--color-*` namespace; **without it Tailwind v4 generates no `bg-card` / `text-muted-foreground` utility at all**, because v4 derives utilities from that namespace rather than from a JS config. Do not remove it.

### Surfaces and text

| Token | Use | Light | Dark |
|---|---|---|---|
| `background` | Page canvas — the shell and full-page layouts only | `#f6f8fb` | `#0b1220` |
| `foreground` | Primary text, headings | `#0b1220` | `#f8fafc` |
| `card` | Raised surfaces: cards, nav bars, dropdowns, modals | `#ffffff` | `#111a2b` |
| `muted` | Subtle fills: table headers, inert chips, wells | `#eff3f9` | `#172234` |
| `muted-foreground` | Secondary text, icons, placeholders | `#5b6b84` | `#94a3b8` |
| `accent` | Hover fill for rows and ghost buttons | `#eff3f9` | `#1b2536` |
| `secondary` | Low-emphasis button fill | `#eff3f9` | `#1b2536` |
| `border` | Default hairline | `#e3e8f0` | `#223148` |
| `border-strong` | Emphasised divider, control outline | `#cbd5e1` | `#33455f` |
| `input` | Form control border | `#cbd5e1` | `#33455f` |
| `ring` | Focus ring | `#0b69de` | `#2d8cff` |

**Depth rule:** `background` is always *behind* `card`. Never use `muted` as a page background — in dark mode it is lighter than `card`, which inverts the intended depth.

### Brand

Constant across themes, so the mark never shifts hue. Sampled from the app icon.

| Token | Value | Use |
|---|---|---|
| `brand` | `#2d8cff` | The "Dash" in the wordmark, brand accents |
| `brand-green` | `#22c55e` | Brand accent (the icon's rising bar) |
| `brand-navy` | `#0b1220` | The icon field; also the dark-mode `background` |

### Intent colours

Each has four slots: solid fill (`X`), label on that fill (`X-foreground`), tinted background (`X-subtle`), and readable text on the tint (`X-strong`).

| Token | Meaning |
|---|---|
| `primary` | The main action. Light mode uses a deeper azure (`#0b69de`) than `brand` so white labels clear AA at 5.13:1; dark mode uses the true brand azure with a navy label (5.75:1). |
| `primary-hover` / `primary-subtle` | Primary hover fill / tint for selected nav and info chips |
| `destructive` | Destroys data or revokes access |
| `success` | Completed, healthy, passing |
| `warning` | Needs attention, stale, paused |
| `info` | Neutral notice, in-flight |
| `assistant` | AI surfaces only — violet, so the assistant reads as a distinct mode |

Every pair above is contrast-checked against its own surface at ≥ 4.5:1.

### Per-org theming

`(platform)/layout.tsx` overrides `--primary`, `--primary-hover`, and `--ring` from the org's `primary_color`. It writes `--primary`, **not** `--color-primary`: `@theme inline` resolves the namespace at build time, so only the underlying variable is overridable at runtime. The value is validated against a hex allowlist before interpolation — it lands inside a `<style>` block, where arbitrary text is a stored-XSS sink.

## Primitives

All exported from `@/components/ui`.

| Primitive | File | Notes |
|---|---|---|
| `Button`, `buttonVariants` | `Button.tsx` | Variants: `primary` `secondary` `outline` `ghost` `destructive` `destructive-ghost` `link`. Sizes: `sm` `md` `lg` `icon` `icon-sm`. `isLoading` shows a spinner and disables. Use `buttonVariants({...})` to style a `<Link>`. |
| `Card` + `CardHeader/Title/Description/Content/Footer` | `Card.tsx` | `interactive` for clickable cards |
| `Input`, `Textarea`, `Select`, `Label`, `Field`, `FieldError`, `controlClasses` | `Input.tsx` | `Field` is label + control + hint/error with correct spacing. All three controls take `size="sm"` for inline/toolbar density. `Select` redraws the arrow, which the UA renders in the OS light colour regardless of theme, and takes `wrapperClassName` for layout classes (`ml-auto`, `flex-1`) — the positioning wrapper is the flex child, not the `<select>`. Its `size` prop replaces the native visible-row count, which is meaningless here. |
| `Badge`, `StatusBadge`, `statusTone` | `Badge.tsx` | `StatusBadge` maps ~35 known states (`completed`, `failed`, `running`, …) to a tone. Extend `STATUS_TONES` rather than picking a tone per page. |
| `PageHeader`, `SectionHeader` | `PageHeader.tsx` | Title + description + actions; `PageHeader` owns the route's `<h1>` |
| `EmptyState`, `ErrorState` | `EmptyState.tsx` | `description` is required by design |
| `Table*` | `Table.tsx` | `TableContainer` supplies the horizontal scroll wide tables need — the page body must never scroll sideways |
| `Alert`, `Skeleton`, `Spinner`, `LoadingRows` | `Feedback.tsx` | `Alert` for persistent in-page messages; sonner toasts for transient ones |
| `Tabs` | `Tabs.tsx` | Appearance + full ARIA tabs keyboard support; pages keep their own active-tab state |
| `Brand`, `APP_NAME` | `Brand.tsx` | Icon + "Sec Dash" lockup; falls back to the org's logo and name when white-labelled |
| `Modal`, `DetailList`, `DetailRow` | `Modal.tsx` | Radix dialog — focus trap and Escape included. Never hand-roll a `fixed inset-0` overlay |
| `Toggle`, `ToggleRow` | `Toggle.tsx` | Switch control |
| `Avatar`, `AvatarGroup`, `userInitials`, `avatarSrc` | `Avatar.tsx` | A person, everywhere one is shown. Uploaded image or initials on a colour **hashed from the email**, so the same person is the same colour on every screen — never index- or random-based, or the avatar reshuffles when a list reorders and stops being recognisable. Sizes `xs`–`xl`; `AvatarGroup` overlaps a team and adds a `+N` chip. |

### Composite admin components

| Component | File | Notes |
|---|---|---|
| `ProviderConnectionForm` | `components/admin/ProviderConnectionForm.tsx` | The "connect to an external system" dialog shared by the admin connection pages (pipelines, BI, billing). Renders name + grouped provider picker + the provider's metadata-declared fields + active toggle, and handles write-only secrets (blank on edit = keep stored value). Pass `providerGroups` for the `<optgroup>` layout and an optional `notice` callout; everything else is uniform. Adding a provider needs no UI change — the fields come from `ProviderMeta`. |

### Example

```tsx
import { Button, Card, EmptyState, PageHeader, StatusBadge } from '@/components/ui'

<PageHeader
  title="Data Exports"
  description="Manage export jobs and schedules"
  actions={<Button onClick={openDialog}><Plus aria-hidden />New Schedule</Button>}
/>
<Card className="p-5">
  <StatusBadge status={job.status} />
</Card>
```

## Error and loading boundaries

| File | Covers |
|---|---|
| `app/error.tsx` | Any route render error; offers `reset()` and shows the digest |
| `app/global-error.tsx` | Failure in the root layout itself — renders its own `<html>` with inline styles, since the stylesheet import is what failed |
| `app/not-found.tsx` | 404s, including feature-flagged routes that `notFound()` |
| `app/(platform)/loading.tsx`, `app/admin/loading.tsx` | Streaming fallback while a Server Component awaits the API |

## Icons

[lucide-react](https://lucide.dev) only. Size via the `[&_svg]:size-*` already baked into `Button`, or `h-4 w-4` inline. Decorative icons take `aria-hidden`; an icon-only control needs `aria-label`.

## Adding a token

1. Add the variable to **both** `:root` and `.dark` in `globals.css`.
2. Map it in the `@theme inline` block — otherwise no utility is generated.
3. Check contrast against the surface it sits on (≥ 4.5:1 for text, ≥ 3:1 for UI edges).
4. Document it in the table above.
