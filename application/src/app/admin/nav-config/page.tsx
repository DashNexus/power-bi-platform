'use client'

/**
 * Portal navigation configuration.
 *
 * Admins build the top navigation bar every user in the organisation sees. An
 * item is either a direct link or a dropdown grouping several links, and an
 * href can point at any internal route, a specific dashboard, page, data
 * dictionary or pipeline, or an external URL. Leaving the list empty restores
 * the default navigation.
 *
 * What is configured here is what is *offered*, not what is granted: PortalNav
 * filters every link through `isHrefAccessible`, so naming a dashboard here
 * shows it only to people who could already open it.
 */
import { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import {
  Plus,
  Trash2,
  ChevronDown,
  ChevronUp,
  GripVertical,
  Link as LinkIcon,
  Menu,
} from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { Alert, Button, Card, EmptyState, Input, LoadingRows, PageHeader, Select } from '@/components/ui'
import { cn } from '@/lib/utils'

interface NavLink {
  label: string
  href: string
}

interface NavItem {
  type: 'link' | 'dropdown'
  label: string
  href?: string
  items?: NavLink[]
}

interface Suggestion {
  label: string
  href: string
  category: string
}

/** The routes this build ships. Kept in step with `app/(platform)`. */
const STATIC_SUGGESTIONS: Suggestion[] = [
  { label: 'Home', href: '/home', category: 'Internal pages' },
  { label: 'All Resources', href: '/resources', category: 'Internal pages' },
  { label: 'Dashboards', href: '/dashboard', category: 'Internal pages' },
  { label: 'Pages', href: '/pages', category: 'Internal pages' },
  { label: 'Data Dictionary', href: '/data-dicts', category: 'Internal pages' },
  { label: 'Data Pipelines', href: '/pipelines', category: 'Internal pages' },
  { label: 'Data Exports', href: '/exports', category: 'Internal pages' },
  { label: 'Settings', href: '/settings', category: 'Internal pages' },
]

function emptyLink(): NavItem {
  return { type: 'link', label: '', href: '' }
}

function emptyDropdown(): NavItem {
  return { type: 'dropdown', label: '', items: [{ label: '', href: '' }] }
}

/**
 * Reject an href the API would reject, before the round-trip.
 *
 * Mirrors `_validate_href` in `api/app/schemas/nav_config.py`. The API is the
 * authority — this exists so a mistake is caught next to the field that caused
 * it rather than as one message covering a whole failed save.
 */
function hrefProblem(href: string): string | null {
  const trimmed = href.trim()
  if (!trimmed) return 'needs a target'
  if (/^https?:\/\//i.test(trimmed)) return null
  if (trimmed.startsWith('//')) return 'looks internal but points off-site'
  if (!trimmed.startsWith('/')) return 'must start with / or be an http(s) URL'
  return null
}

/** Every problem in the current draft, as messages naming the item. */
function validate(items: NavItem[]): string[] {
  const problems: string[] = []
  items.forEach((item, i) => {
    const name = item.label.trim() || `item ${i + 1}`
    if (!item.label.trim()) problems.push(`Item ${i + 1} needs a label.`)
    if (item.type === 'link') {
      const problem = hrefProblem(item.href ?? '')
      if (problem) problems.push(`"${name}" ${problem}.`)
      return
    }
    const children = item.items ?? []
    if (children.length === 0) {
      problems.push(`"${name}" is a dropdown, so it needs at least one item.`)
    }
    children.forEach((child, ci) => {
      const childName = child.label.trim() || `entry ${ci + 1}`
      if (!child.label.trim()) problems.push(`Entry ${ci + 1} of "${name}" needs a label.`)
      const problem = hrefProblem(child.href)
      if (problem) problems.push(`"${childName}" in "${name}" ${problem}.`)
    })
  })
  return problems
}

// ─── HrefInput ────────────────────────────────────────────────────────────────

interface HrefInputProps {
  value: string
  onChange: (v: string) => void
  placeholder?: string
  className?: string
  suggestions: Suggestion[]
  invalid?: boolean
  'aria-label': string
}

function HrefInput({
  value,
  onChange,
  placeholder,
  className,
  suggestions,
  invalid,
  'aria-label': ariaLabel,
}: HrefInputProps) {
  const [open, setOpen] = useState(false)

  const q = value.toLowerCase()
  const filtered = suggestions.filter(
    s =>
      !q ||
      s.label.toLowerCase().includes(q) ||
      s.href.toLowerCase().includes(q) ||
      s.category.toLowerCase().includes(q),
  )

  const groups = filtered.reduce<Record<string, Suggestion[]>>((acc, s) => {
    ;(acc[s.category] ??= []).push(s)
    return acc
  }, {})

  return (
    <div className="relative flex-1">
      <Input
        type="text"
        value={value}
        onChange={e => onChange(e.target.value)}
        onFocus={() => setOpen(true)}
        // Delayed so a suggestion's mousedown lands before the list unmounts.
        onBlur={() => setTimeout(() => setOpen(false), 150)}
        placeholder={placeholder}
        aria-label={ariaLabel}
        aria-invalid={invalid || undefined}
        className={cn('font-mono', invalid && 'border-destructive-strong', className)}
        autoComplete="off"
      />
      {open && Object.keys(groups).length > 0 && (
        <div className="absolute left-0 right-0 top-full z-50 mt-1 max-h-72 overflow-y-auto rounded-lg border border-border bg-card shadow-lg">
          {Object.entries(groups).map(([category, items]) => (
            <div key={category}>
              <div className="sticky top-0 border-b border-border bg-muted px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
                {category}
              </div>
              {items.map(s => (
                <button
                  key={s.href}
                  type="button"
                  onMouseDown={() => onChange(s.href)}
                  className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-sm transition-colors hover:bg-primary-subtle"
                >
                  <span className="truncate font-medium text-foreground">{s.label}</span>
                  <span className="shrink-0 font-mono text-xs text-muted-foreground">{s.href}</span>
                </button>
              ))}
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ─── NavItemEditor ────────────────────────────────────────────────────────────

interface NavItemEditorProps {
  item: NavItem
  index: number
  total: number
  suggestions: Suggestion[]
  onChange: (item: NavItem) => void
  onRemove: () => void
  onMove: (direction: 'up' | 'down') => void
}

function NavItemEditor({
  item,
  index,
  total,
  suggestions,
  onChange,
  onRemove,
  onMove,
}: NavItemEditorProps) {
  const position = `item ${index + 1}`

  function addChild() {
    onChange({ ...item, items: [...(item.items ?? []), { label: '', href: '' }] })
  }

  function updateChild(i: number, patch: Partial<NavLink>) {
    const items = (item.items ?? []).map((c, ci) => (ci === i ? { ...c, ...patch } : c))
    onChange({ ...item, items })
  }

  function removeChild(i: number) {
    onChange({ ...item, items: (item.items ?? []).filter((_, ci) => ci !== i) })
  }

  return (
    <Card className="p-4">
      <div className="flex items-start gap-3">
        <GripVertical className="mt-2.5 h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />

        <div className="flex-1 space-y-3">
          <div className="flex items-center gap-3">
            <Select
              value={item.type}
              aria-label={`Type of nav ${position}`}
              className="w-auto"
              onChange={e => {
                const t = e.target.value as NavItem['type']
                // Switching type keeps the label and drops the half that no
                // longer applies, so the API's shape check cannot fail on a
                // leftover field the editor is no longer showing.
                onChange(
                  t === 'dropdown'
                    ? {
                        type: 'dropdown',
                        label: item.label,
                        items: item.items ?? [{ label: '', href: '' }],
                      }
                    : { type: 'link', label: item.label, href: item.href ?? '' },
                )
              }}
            >
              <option value="link">Link</option>
              <option value="dropdown">Dropdown</option>
            </Select>
            <Input
              type="text"
              value={item.label}
              onChange={e => onChange({ ...item, label: e.target.value })}
              placeholder="Label"
              aria-label={`Label for nav ${position}`}
              className="flex-1"
            />
          </div>

          {item.type === 'link' && (
            <div className="flex items-center gap-2">
              <LinkIcon className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
              <HrefInput
                value={item.href ?? ''}
                onChange={v => onChange({ ...item, href: v })}
                placeholder="/dashboard or https://…"
                aria-label={`Link target for nav ${position}`}
                suggestions={suggestions}
                invalid={Boolean(item.href) && hrefProblem(item.href ?? '') !== null}
              />
            </div>
          )}

          {item.type === 'dropdown' && (
            <div className="space-y-2 border-l-2 border-border pl-4">
              {(item.items ?? []).map((child, ci) => (
                <div key={ci} className="flex items-center gap-2">
                  <Input
                    type="text"
                    value={child.label}
                    onChange={e => updateChild(ci, { label: e.target.value })}
                    placeholder="Item label"
                    aria-label={`Label for nav ${position} entry ${ci + 1}`}
                    className="w-36"
                  />
                  <HrefInput
                    value={child.href}
                    onChange={v => updateChild(ci, { href: v })}
                    placeholder="/dashboard/1"
                    aria-label={`Link target for nav ${position} entry ${ci + 1}`}
                    suggestions={suggestions}
                    invalid={Boolean(child.href) && hrefProblem(child.href) !== null}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    aria-label={`Remove nav ${position} entry ${ci + 1}`}
                    onClick={() => removeChild(ci)}
                  >
                    <Trash2 className="h-3.5 w-3.5 text-destructive-strong" aria-hidden />
                  </Button>
                </div>
              ))}
              <Button variant="ghost" size="sm" onClick={addChild}>
                <Plus className="h-3.5 w-3.5" aria-hidden />
                Add item
              </Button>
            </div>
          )}
        </div>

        <div className="flex shrink-0 flex-col items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            disabled={index === 0}
            onClick={() => onMove('up')}
            title="Move up"
            aria-label={`Move nav ${position} up`}
          >
            <ChevronUp className="h-3.5 w-3.5" aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            disabled={index === total - 1}
            onClick={() => onMove('down')}
            title="Move down"
            aria-label={`Move nav ${position} down`}
          >
            <ChevronDown className="h-3.5 w-3.5" aria-hidden />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={onRemove}
            title="Remove"
            aria-label={`Remove nav ${position}`}
          >
            <Trash2 className="h-3.5 w-3.5 text-destructive-strong" aria-hidden />
          </Button>
        </div>
      </div>
    </Card>
  )
}

// ─── Page ─────────────────────────────────────────────────────────────────────

export default function NavConfigPage() {
  const { data: session } = useSession({ required: true })
  const token = session?.user.access_token
  const [items, setItems] = useState<NavItem[]>([])
  const [suggestions, setSuggestions] = useState<Suggestion[]>(STATIC_SUGGESTIONS)
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    if (!token) return
    const apiFetch = createClientFetch(token)
    // Settled rather than all: the suggestion lists are a convenience, and one
    // of them failing must not stop an admin editing the navigation.
    const [saved, dashboards, pages, dictionaries, pipelines] = await Promise.allSettled([
      apiFetch<{ items: NavItem[] }>('/admin/nav-config'),
      apiFetch<{ id: number; name: string }[]>('/dashboards'),
      apiFetch<{ title: string; slug: string }[]>('/pages'),
      apiFetch<{ id: number; name: string }[]>('/data-dictionary/warehouses'),
      apiFetch<{ id: number; name: string }[]>('/data-pipelines'),
    ])

    if (saved.status === 'fulfilled') {
      setItems(saved.value.items)
    } else {
      toast.error(
        saved.reason instanceof Error
          ? saved.reason.message
          : 'Failed to load the navigation config.',
      )
    }

    const dynamic = [...STATIC_SUGGESTIONS]
    if (dashboards.status === 'fulfilled') {
      dashboards.value.forEach(d =>
        dynamic.push({ label: d.name, href: `/dashboard/${d.id}`, category: 'Dashboards' }),
      )
    }
    if (pages.status === 'fulfilled') {
      pages.value.forEach(p =>
        dynamic.push({ label: p.title, href: `/pages/${p.slug}`, category: 'Pages' }),
      )
    }
    if (dictionaries.status === 'fulfilled') {
      dictionaries.value.forEach(d =>
        dynamic.push({ label: d.name, href: `/data-dicts/${d.id}`, category: 'Data Dictionaries' }),
      )
    }
    if (pipelines.status === 'fulfilled') {
      pipelines.value.forEach(p =>
        dynamic.push({ label: p.name, href: `/pipelines/${p.id}`, category: 'Data Pipelines' }),
      )
    }
    setSuggestions(dynamic)
    setLoading(false)
  }, [token])

  useEffect(() => {
    void load()
  }, [load])

  function updateItem(i: number, patch: NavItem) {
    setItems(prev => prev.map((item, idx) => (idx === i ? patch : item)))
  }

  function removeItem(i: number) {
    setItems(prev => prev.filter((_, idx) => idx !== i))
  }

  function moveItem(i: number, direction: 'up' | 'down') {
    setItems(prev => {
      const arr = [...prev]
      const target = direction === 'up' ? i - 1 : i + 1
      if (target < 0 || target >= arr.length) return arr
      ;[arr[i], arr[target]] = [arr[target], arr[i]]
      return arr
    })
  }

  const problems = validate(items)

  async function handleSave() {
    if (!token || problems.length > 0) return
    setSaving(true)
    try {
      const apiFetch = createClientFetch(token)
      const saved = await apiFetch<{ items: NavItem[] }>('/admin/nav-config', {
        method: 'PUT',
        body: JSON.stringify({ items }),
      })
      // Take the API's copy back: it trims labels and hrefs, and showing the
      // draft instead would hide that from the person who saved it.
      setItems(saved.items)
      toast.success(
        saved.items.length === 0
          ? 'Navigation reset — everyone sees the default links.'
          : 'Navigation saved.',
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save the navigation.')
    } finally {
      setSaving(false)
    }
  }

  function handleReset() {
    if (!confirm('Reset to the default navigation? This removes every configured item.')) return
    setItems([])
  }

  return (
    <div className="max-w-5xl space-y-6">
      <PageHeader
        title="Navigation Config"
        description="Build the top navigation bar shown to everyone in this organisation. Add links and dropdowns pointing at dashboards, pages, data dictionaries, pipelines, or any URL. Leave it empty to use the default navigation."
      />

      {loading ? (
        <Card className="p-6">
          <LoadingRows rows={3} />
        </Card>
      ) : (
        <>
          {items.length > 0 && (
            <Alert tone="info">
              A link is only shown to people who can already open its destination — configuring one
              here does not grant access to it.
            </Alert>
          )}

          <div className="space-y-3">
            {items.map((item, i) => (
              <NavItemEditor
                key={i}
                item={item}
                index={i}
                total={items.length}
                suggestions={suggestions}
                onChange={patch => updateItem(i, patch)}
                onRemove={() => removeItem(i)}
                onMove={dir => moveItem(i, dir)}
              />
            ))}

            {items.length === 0 && (
              <Card className="p-6">
                <EmptyState
                  icon={Menu}
                  title="No navigation items configured"
                  description="Everyone is seeing the default navigation. Add a link or a dropdown below to build a custom nav bar — nothing changes for anyone until you save."
                />
              </Card>
            )}
          </div>

          <div className="flex items-center gap-2">
            <Button variant="outline" onClick={() => setItems(prev => [...prev, emptyLink()])}>
              <Plus className="h-4 w-4" aria-hidden />
              Add link
            </Button>
            <Button variant="outline" onClick={() => setItems(prev => [...prev, emptyDropdown()])}>
              <ChevronDown className="h-4 w-4" aria-hidden />
              Add dropdown
            </Button>
          </div>

          {problems.length > 0 && (
            <Alert tone="danger">
              <p className="font-medium">Fix these before saving:</p>
              <ul className="mt-1 list-disc space-y-0.5 pl-5">
                {problems.map(problem => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            </Alert>
          )}

          <div className="flex items-center gap-3 border-t border-border pt-5">
            <Button
              onClick={() => void handleSave()}
              isLoading={saving}
              disabled={problems.length > 0}
              title={problems.length > 0 ? 'Fix the problems listed above first' : undefined}
            >
              Save navigation
            </Button>
            <Button variant="outline" onClick={handleReset} disabled={items.length === 0}>
              Reset to default
            </Button>
          </div>
        </>
      )}
    </div>
  )
}
