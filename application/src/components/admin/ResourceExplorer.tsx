'use client'

/**
 * Shared search + view-mode controls for admin resource list pages.
 *
 * Pages call useResourceView(key) for persisted { query, view } state, filter
 * their items with filterBySearch, and render <ResourceToolbar/> above either a
 * card grid or a list. Keeps each page in control of its card/row markup while
 * sharing search, the card/list toggle, and persistence.
 */
import { useEffect, useState } from 'react'
import { LayoutGrid, List as ListIcon, Search } from 'lucide-react'
import { cn } from '@/lib/utils'

export type ResourceView = 'card' | 'list'

export function useResourceView(key: string, initial: ResourceView = 'list') {
  const [view, setViewState] = useState<ResourceView>(initial)
  const [query, setQuery] = useState('')

  useEffect(() => {
    const stored = localStorage.getItem(`resource-view:${key}`)
    if (stored === 'card' || stored === 'list') setViewState(stored)
  }, [key])

  function setView(next: ResourceView) {
    setViewState(next)
    localStorage.setItem(`resource-view:${key}`, next)
  }

  return { view, setView, query, setQuery }
}

/** Case-insensitive substring filter over a string accessor. */
export function filterBySearch<T>(items: T[], query: string, accessor: (item: T) => string): T[] {
  const q = query.trim().toLowerCase()
  if (!q) return items
  return items.filter(item => accessor(item).toLowerCase().includes(q))
}

interface ResourceToolbarProps {
  query: string
  onQuery: (value: string) => void
  view: ResourceView
  onView: (view: ResourceView) => void
  placeholder?: string
  /** Page-specific filters, rendered between the search box and view toggle. */
  extra?: React.ReactNode
}

export function ResourceToolbar({
  query,
  onQuery,
  view,
  onView,
  placeholder,
  extra,
}: ResourceToolbarProps) {
  return (
    <div className="mb-4 flex items-center gap-2">
      <div className="relative flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <input
          value={query}
          onChange={e => onQuery(e.target.value)}
          placeholder={placeholder ?? 'Search…'}
          className="w-full rounded-lg border border-border-strong bg-card py-1.5 pl-9 pr-3 text-sm outline-none focus:border-primary "
        />
      </div>
      {extra}
      <div className="flex shrink-0 rounded-lg border border-border-strong ">
        {(
          [
            { value: 'list' as const, icon: ListIcon, label: 'List view' },
            { value: 'card' as const, icon: LayoutGrid, label: 'Card view' },
          ]
        ).map(({ value, icon: Icon, label }) => (
          <button
            key={value}
            type="button"
            aria-label={label}
            aria-pressed={view === value}
            onClick={() => onView(value)}
            className={cn(
              'p-2 first:rounded-l-lg last:rounded-r-lg transition-colors',
              view === value
                ? 'bg-primary-subtle text-primary '
                : 'text-muted-foreground hover:bg-accent ',
            )}
          >
            <Icon className="h-4 w-4" />
          </button>
        ))}
      </div>
    </div>
  )
}
