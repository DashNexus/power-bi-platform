'use client'

/**
 * Searchable, switchable browser for a portal resource list.
 *
 * Every portal listing page (dashboards, pages, ERDs, lineages, dictionaries,
 * timelines, the resource grid) shows the same thing: a set of named resources
 * you can open, favourite, and now search. This renders that once.
 *
 * Both the card and list views are built from the same `ResourceItem`, so the
 * two can never drift — a page maps its domain object to `ResourceItem` and
 * gets both layouts, the search box, and the persisted view toggle for free.
 */
import { useMemo, useState } from 'react'
import Link from 'next/link'
import { ExternalLink, LayoutGrid, List, Search, Star } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
  type BadgeProps,
} from '@/components/ui'
import { cn } from '@/lib/utils'
import { useViewMode, type ViewMode } from './useViewMode'

export interface ResourceItem {
  key: string | number
  href: string
  icon: LucideIcon
  title: string
  description?: string | null
  /** Type chip, e.g. "ERD". */
  badge?: { label: string; tone?: BadgeProps['tone'] }
  /** Short facts — "12 tables", "Power BI". Shown under the title and in the list. */
  meta?: string[]
  favorite?: { active: boolean; onToggle: () => void | Promise<void> }
  /** Matched by search but never displayed. */
  searchText?: string
  /** Opens in a new tab. */
  external?: boolean
  /**
   * Bespoke card for this item, used instead of the default in card view.
   *
   * For listings whose card does more than show a name — the dashboard card
   * polls data freshness, for example. The list view always renders from the
   * fields above, so the two views stay consistent either way.
   */
  card?: React.ReactNode
}

interface ResourceBrowserProps {
  items: ResourceItem[]
  /** Stable per-page key for persisting the card/list preference. */
  storageKey: string
  searchPlaceholder?: string
  /** Heading for the list view's primary column. */
  nameColumnLabel?: string
  /** Shown when the page has no resources at all (before searching). */
  emptyState: React.ReactNode
  /** Tailwind columns for the card grid. */
  gridClassName?: string
  /** Rendered to the left of the view toggle — page-specific filters. */
  toolbarExtra?: React.ReactNode
  defaultView?: ViewMode
}

function FavoriteButton({ favorite, title }: { favorite: NonNullable<ResourceItem['favorite']>; title: string }) {
  const [toggling, setToggling] = useState(false)

  async function handleClick(e: React.MouseEvent) {
    // The whole card is a link; favouriting must not navigate.
    e.preventDefault()
    e.stopPropagation()
    setToggling(true)
    try {
      await favorite.onToggle()
    } finally {
      setToggling(false)
    }
  }

  return (
    <button
      type="button"
      onClick={handleClick}
      disabled={toggling}
      aria-pressed={favorite.active}
      aria-label={
        favorite.active ? `Remove ${title} from favourites` : `Add ${title} to favourites`
      }
      className={cn(
        'shrink-0 rounded-full p-1 transition-colors disabled:opacity-50',
        favorite.active
          ? 'text-warning hover:text-warning-strong'
          : 'text-muted-foreground hover:text-warning',
      )}
    >
      <Star className={cn('h-4 w-4', favorite.active && 'fill-current')} aria-hidden />
    </button>
  )
}

function ResourceCardView({ item }: { item: ResourceItem }) {
  const Icon = item.icon
  return (
    <Link
      href={item.href}
      target={item.external ? '_blank' : undefined}
      rel={item.external ? 'noreferrer' : undefined}
      className="group relative flex flex-col rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:border-border-strong hover:shadow-md"
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-info-strong">
          <Icon className="h-5 w-5" aria-hidden />
        </div>
        {item.favorite && <FavoriteButton favorite={item.favorite} title={item.title} />}
      </div>
      <div className="mt-3 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="line-clamp-1 font-medium text-foreground transition-colors group-hover:text-primary">
            {item.title}
          </h3>
          <ExternalLink
            className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100"
            aria-hidden
          />
        </div>
        {item.description && (
          <p className="mt-1 line-clamp-2 text-sm text-muted-foreground">{item.description}</p>
        )}
      </div>
      {(item.badge || item.meta?.length) && (
        <div className="mt-3 flex flex-wrap items-center gap-1.5">
          {item.badge && <Badge tone={item.badge.tone ?? 'info'}>{item.badge.label}</Badge>}
          {item.meta?.map(m => (
            <span key={m} className="text-xs text-muted-foreground">
              {m}
            </span>
          ))}
        </div>
      )}
    </Link>
  )
}

export function ResourceBrowser({
  items,
  storageKey,
  searchPlaceholder = 'Search…',
  nameColumnLabel = 'Name',
  emptyState,
  gridClassName = 'grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4',
  toolbarExtra,
  defaultView = 'card',
}: ResourceBrowserProps) {
  const [view, setView] = useViewMode(storageKey, defaultView)
  const [query, setQuery] = useState('')

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase()
    if (!q) return items
    return items.filter(item =>
      [item.title, item.description, item.searchText, item.badge?.label, ...(item.meta ?? [])]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(q),
    )
  }, [items, query])

  // Nothing to browse at all — the page's own empty state, not a search miss.
  if (items.length === 0) return <>{emptyState}</>

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder={searchPlaceholder}
            aria-label={searchPlaceholder}
            className="pl-9"
          />
        </div>
        {toolbarExtra}
        <div
          className="flex items-center rounded-lg border border-border p-0.5"
          role="group"
          aria-label="View mode"
        >
          <Button
            variant={view === 'card' ? 'secondary' : 'ghost'}
            size="icon-sm"
            onClick={() => setView('card')}
            aria-pressed={view === 'card'}
            aria-label="Card view"
            title="Card view"
          >
            <LayoutGrid aria-hidden />
          </Button>
          <Button
            variant={view === 'list' ? 'secondary' : 'ghost'}
            size="icon-sm"
            onClick={() => setView('list')}
            aria-pressed={view === 'list'}
            aria-label="List view"
            title="List view"
          >
            <List aria-hidden />
          </Button>
        </div>
      </div>

      <p className="sr-only" role="status">
        {filtered.length} of {items.length} shown
      </p>

      {filtered.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={Search}
            title="No matches"
            description={`Nothing here matches “${query.trim()}”. Try a shorter or different search term.`}
            action={
              <Button variant="outline" onClick={() => setQuery('')}>
                Clear search
              </Button>
            }
          />
        </Card>
      ) : view === 'card' ? (
        <div className={gridClassName}>
          {filtered.map(item =>
            item.card ? (
              <div key={item.key}>{item.card}</div>
            ) : (
              <ResourceCardView key={item.key} item={item} />
            ),
          )}
        </div>
      ) : (
        <Card className="overflow-hidden">
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  {items.some(i => i.favorite) && (
                    <TableHeaderCell className="w-10">
                      <span className="sr-only">Favourite</span>
                    </TableHeaderCell>
                  )}
                  <TableHeaderCell>{nameColumnLabel}</TableHeaderCell>
                  <TableHeaderCell>Description</TableHeaderCell>
                  <TableHeaderCell>Details</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {filtered.map(item => {
                  const Icon = item.icon
                  return (
                    <TableRow key={item.key} interactive>
                      {items.some(i => i.favorite) && (
                        <TableCell>
                          {item.favorite && (
                            <FavoriteButton favorite={item.favorite} title={item.title} />
                          )}
                        </TableCell>
                      )}
                      <TableCell>
                        <Link
                          href={item.href}
                          target={item.external ? '_blank' : undefined}
                          rel={item.external ? 'noreferrer' : undefined}
                          className="flex items-center gap-2 font-medium text-foreground hover:text-primary"
                        >
                          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                          {item.title}
                        </Link>
                      </TableCell>
                      <TableCell muted className="max-w-md">
                        <span className="line-clamp-1">{item.description || '—'}</span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          {item.badge && (
                            <Badge tone={item.badge.tone ?? 'info'}>{item.badge.label}</Badge>
                          )}
                          {item.meta?.map(m => (
                            <span key={m} className="text-xs text-muted-foreground">
                              {m}
                            </span>
                          ))}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}
    </div>
  )
}
