'use client'

/**
 * Filter panel for user-facing dashboard controls.
 *
 * Renders one control per filter defined in the dashboard config.
 * String/date/number filters use native inputs; select filters use a
 * dropdown populated from the filter's default_value JSON array.
 * Shows a Reset button whenever any value differs from its default.
 */
import { cn } from '@/lib/utils'

interface Filter {
  filter_key: string
  filter_label: string
  filter_type: 'string' | 'date' | 'number' | 'select'
  default_value: string | null
  is_required: boolean
}

interface FilterPanelProps {
  filters: Filter[]
  values: Record<string, string>
  onChange: (key: string, value: string) => void
}

export function FilterPanel({ filters, values, onChange }: FilterPanelProps) {
  const isDirty = filters.some(f => {
    const current = values[f.filter_key] ?? ''
    const defaultVal = f.default_value ?? ''
    return current !== defaultVal
  })

  function handleReset() {
    filters.forEach(f => {
      onChange(f.filter_key, f.default_value ?? '')
    })
  }

  if (filters.length === 0) return null

  return (
    <div className="mb-4 flex flex-wrap items-end gap-3 rounded-xl border border-border bg-card p-3 shadow-sm">
      {filters.map(filter => (
        <div key={filter.filter_key} className="flex flex-col gap-1 min-w-[160px]">
          <label
            htmlFor={`filter-${filter.filter_key}`}
            className="text-xs font-medium text-muted-foreground"
          >
            {filter.filter_label}
            {filter.is_required && (
              <span className="ml-0.5 text-destructive" aria-hidden="true">*</span>
            )}
          </label>

          {filter.filter_type === 'select' ? (
            <SelectFilter
              id={`filter-${filter.filter_key}`}
              filterKey={filter.filter_key}
              defaultValue={filter.default_value}
              value={values[filter.filter_key] ?? ''}
              onChange={onChange}
            />
          ) : (
            <input
              id={`filter-${filter.filter_key}`}
              type={
                filter.filter_type === 'date'
                  ? 'date'
                  : filter.filter_type === 'number'
                    ? 'number'
                    : 'text'
              }
              value={values[filter.filter_key] ?? ''}
              required={filter.is_required}
              onChange={e => onChange(filter.filter_key, e.target.value)}
              className={cn(
                'rounded-lg border border-border-strong bg-card px-3 py-1.5 text-sm shadow-sm',
                'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
              )}
            />
          )}
        </div>
      ))}

      {isDirty && (
        <button
          type="button"
          onClick={handleReset}
          className={cn(
            'self-end rounded-lg border border-border-strong bg-card px-3 py-1.5 text-sm font-medium text-muted-foreground',
            'hover:bg-accent transition-colors',
          )}
        >
          Reset
        </button>
      )}
    </div>
  )
}

interface SelectFilterProps {
  id: string
  filterKey: string
  defaultValue: string | null
  value: string
  onChange: (key: string, value: string) => void
}

function SelectFilter({ id, filterKey, defaultValue, value, onChange }: SelectFilterProps) {
  // default_value is a JSON array of option strings when filter_type is 'select'
  let options: string[] = []
  try {
    const parsed = JSON.parse(defaultValue ?? '[]')
    if (Array.isArray(parsed)) options = parsed.map(String)
  } catch {
    options = defaultValue ? [defaultValue] : []
  }

  return (
    <select
      id={id}
      value={value}
      onChange={e => onChange(filterKey, e.target.value)}
      className={cn(
        'rounded-lg border border-border-strong bg-card px-3 py-1.5 text-sm shadow-sm',
        'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
      )}
    >
      <option value="">All</option>
      {options.map(opt => (
        <option key={opt} value={opt}>
          {opt}
        </option>
      ))}
    </select>
  )
}
