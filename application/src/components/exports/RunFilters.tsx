'use client'

/**
 * Search and filter controls for a run log.
 *
 * Shared by the Run History tab and the per-report history panel under the SQL
 * Reports tab, so the two behave identically. The filters are sent to the API
 * rather than applied to the rows already fetched: a client-side filter over
 * the most recent page would answer "no matches" for a run that is sitting in
 * the database just past the limit.
 */
import { useEffect, useState } from 'react'
import { Search, X } from 'lucide-react'
import type { RunFilterState } from '@/components/exports/types'
import { EMPTY_RUN_FILTERS, hasRunFilters } from '@/components/exports/types'
import { Button, Input, Select } from '@/components/ui'

interface RunFiltersProps {
  value: RunFilterState
  onChange: (next: RunFilterState) => void
  /** Placeholder for the text box — the two run logs search different things. */
  searchPlaceholder?: string
  /** Number of rows currently shown, for the result count. */
  resultCount: number
}

const STATUSES = [
  { value: '', label: 'Any status' },
  { value: 'completed', label: 'Completed' },
  { value: 'failed', label: 'Failed' },
  { value: 'running', label: 'Running' },
  { value: 'pending', label: 'Pending' },
] as const

const TRIGGERS = [
  { value: '', label: 'Any trigger' },
  { value: 'manual', label: 'Manual' },
  { value: 'schedule', label: 'Scheduled' },
] as const

/** Long enough to stop firing a request per keystroke, short enough to feel live. */
const DEBOUNCE_MS = 300

export function RunFilters({
  value,
  onChange,
  searchPlaceholder = 'Search runs…',
  resultCount,
}: RunFiltersProps) {
  // The text box is uncontrolled with respect to the committed filter so typing
  // stays responsive while the request it triggers is still in flight.
  const [text, setText] = useState(value.search)

  useEffect(() => {
    if (text === value.search) return
    const id = setTimeout(() => onChange({ ...value, search: text }), DEBOUNCE_MS)
    return () => clearTimeout(id)
  }, [text, value, onChange])

  // A filter cleared from outside (the Clear button) has to reach the input.
  useEffect(() => {
    if (value.search === '') setText('')
  }, [value.search])

  const active = hasRunFilters(value)

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="relative min-w-48 flex-1">
        <Search
          className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          aria-hidden
        />
        <Input
          type="search"
          value={text}
          onChange={e => setText(e.target.value)}
          placeholder={searchPlaceholder}
          aria-label="Search runs"
          className="pl-8"
        />
      </div>

      <Select
        value={value.status}
        onChange={e => onChange({ ...value, status: e.target.value })}
        aria-label="Filter by status"
        className="w-auto"
      >
        {STATUSES.map(s => (
          <option key={s.value} value={s.value}>
            {s.label}
          </option>
        ))}
      </Select>

      <Select
        value={value.triggerType}
        onChange={e => onChange({ ...value, triggerType: e.target.value })}
        aria-label="Filter by trigger"
        className="w-auto"
      >
        {TRIGGERS.map(t => (
          <option key={t.value} value={t.value}>
            {t.label}
          </option>
        ))}
      </Select>

      {active && (
        <>
          <span className="text-xs text-muted-foreground">
            {resultCount} {resultCount === 1 ? 'run' : 'runs'}
          </span>
          <Button variant="ghost" size="sm" onClick={() => onChange(EMPTY_RUN_FILTERS)}>
            <X className="h-3.5 w-3.5" aria-hidden />
            Clear
          </Button>
        </>
      )}
    </div>
  )
}
