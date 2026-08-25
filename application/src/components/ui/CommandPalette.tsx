'use client'

/**
 * Global command palette (⌘K / Ctrl+K).
 *
 * Searches dashboards and pages via GET /search?q=. Opens as a modal overlay.
 * Controlled externally — parent manages open/close state.
 */

import { useState, useEffect, useRef, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { Search, LayoutDashboard, FileText, X } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { cn } from '@/lib/utils'

interface SearchResult {
  type: 'dashboard' | 'page'
  id: number
  title: string
  description: string | null
  href: string
  label: string
}

interface SearchResponse {
  results: SearchResult[]
  query: string
}

interface CommandPaletteProps {
  open: boolean
  onClose: () => void
  accessToken: string
}

const TYPE_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  dashboard: LayoutDashboard,
  page: FileText,
}

function ResultItem({
  result,
  active,
  onSelect,
}: {
  result: SearchResult
  active: boolean
  onSelect: () => void
}) {
  const Icon = TYPE_ICONS[result.type] ?? FileText
  return (
    <button
      type="button"
      onMouseDown={onSelect}
      className={cn(
        'flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left transition-colors',
        active ? 'bg-primary-subtle text-info-strong' : 'hover:bg-accent text-foreground',
      )}
    >
      <Icon className={cn('h-4 w-4 shrink-0', active ? 'text-primary' : 'text-muted-foreground')} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{result.title}</p>
        {result.description && (
          <p className="truncate text-xs text-muted-foreground">{result.description}</p>
        )}
      </div>
      <span
        className={cn(
          'shrink-0 rounded-full px-2 py-0.5 text-xs font-medium capitalize',
          active ? 'bg-primary-subtle text-info-strong' : 'bg-muted text-muted-foreground',
        )}
      >
        {result.label}
      </span>
    </button>
  )
}

export function CommandPalette({ open, onClose, accessToken }: CommandPaletteProps) {
  const router = useRouter()
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<SearchResult[]>([])
  const [activeIndex, setActiveIndex] = useState(0)
  const [loading, setLoading] = useState(false)
  const inputRef = useRef<HTMLInputElement>(null)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const apiFetch = createClientFetch(accessToken)

  // Focus input when opened
  useEffect(() => {
    if (open) {
      setQuery('')
      setResults([])
      setActiveIndex(0)
      setTimeout(() => inputRef.current?.focus(), 50)
    }
  }, [open])

  // Debounced search
  const runSearch = useCallback(
    (q: string) => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
      if (q.length < 2) {
        setResults([])
        setLoading(false)
        return
      }
      setLoading(true)
      debounceRef.current = setTimeout(async () => {
        try {
          const data = await apiFetch<SearchResponse>(`/search?q=${encodeURIComponent(q)}`)
          setResults(data.results)
          setActiveIndex(0)
        } catch {
          setResults([])
        } finally {
          setLoading(false)
        }
      }, 280)
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [accessToken],
  )

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const q = e.target.value
    setQuery(q)
    runSearch(q)
  }

  const navigate = useCallback(
    (href: string) => {
      router.push(href)
      onClose()
    },
    [router, onClose],
  )

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Escape') {
      onClose()
      return
    }
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActiveIndex(i => Math.min(i + 1, results.length - 1))
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActiveIndex(i => Math.max(i - 1, 0))
    } else if (e.key === 'Enter' && results[activeIndex]) {
      navigate(results[activeIndex].href)
    }
  }

  if (!open) return null

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-[15vh] px-4"
      onMouseDown={e => { if (e.target === e.currentTarget) onClose() }}
    >
      {/* Backdrop */}
      <div className="absolute inset-0 bg-black/30 backdrop-blur-sm" />

      {/* Panel */}
      <div className="relative w-full max-w-lg rounded-2xl border border-border bg-card shadow-2xl overflow-hidden">
        {/* Search input */}
        <div className="flex items-center gap-3 border-b border-border px-4 py-3">
          <Search className="h-4 w-4 shrink-0 text-muted-foreground" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            placeholder="Search dashboards and pages…"
            className="flex-1 bg-transparent text-sm text-foreground placeholder:text-muted-foreground outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          {loading && (
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-border border-t-blue-600" />
          )}
          <button
            type="button"
            onClick={onClose}
            className="rounded-md p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
            aria-label="Close search"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-80 overflow-y-auto p-2">
          {results.length === 0 && query.length >= 2 && !loading && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No results for &ldquo;{query}&rdquo;
            </p>
          )}
          {results.length === 0 && query.length < 2 && (
            <p className="py-6 text-center text-sm text-muted-foreground">
              Type at least 2 characters to search
            </p>
          )}
          {results.map((result, i) => (
            <ResultItem
              key={`${result.type}-${result.id}`}
              result={result}
              active={i === activeIndex}
              onSelect={() => navigate(result.href)}
            />
          ))}
        </div>

        {/* Footer hint */}
        {results.length > 0 && (
          <div className="border-t border-border px-4 py-2 flex items-center gap-4 text-xs text-muted-foreground">
            <span><kbd className="rounded bg-muted px-1">↑↓</kbd> navigate</span>
            <span><kbd className="rounded bg-muted px-1">↵</kbd> open</span>
            <span><kbd className="rounded bg-muted px-1">Esc</kbd> close</span>
          </div>
        )}
      </div>
    </div>
  )
}
