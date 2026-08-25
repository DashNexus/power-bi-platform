'use client'

/**
 * Underlined tab bar.
 *
 * Deliberately uncontrolled-agnostic and state-free: pages already hold their own
 * `activeTab` state, so this only owns the appearance and the keyboard/ARIA
 * wiring that the hand-rolled versions were missing.
 */
import { cn } from '@/lib/utils'

export interface TabItem<T extends string = string> {
  id: T
  label: string
  /** Trailing count or status pill. */
  badge?: React.ReactNode
  disabled?: boolean
}

interface TabsProps<T extends string> {
  tabs: ReadonlyArray<TabItem<T>>
  active: T
  onChange: (id: T) => void
  className?: string
  'aria-label'?: string
}

export function Tabs<T extends string>({
  tabs,
  active,
  onChange,
  className,
  'aria-label': ariaLabel = 'Sections',
}: TabsProps<T>) {
  const enabled = tabs.filter(t => !t.disabled)

  // Left/Right move between tabs; Home/End jump to the ends. Matches the ARIA
  // tabs pattern, which the previous plain-<button> rows did not implement.
  function handleKeyDown(event: React.KeyboardEvent<HTMLDivElement>) {
    const delta = event.key === 'ArrowRight' ? 1 : event.key === 'ArrowLeft' ? -1 : 0
    if (!delta && event.key !== 'Home' && event.key !== 'End') return
    event.preventDefault()
    const current = enabled.findIndex(t => t.id === active)
    const next =
      event.key === 'Home'
        ? 0
        : event.key === 'End'
          ? enabled.length - 1
          : (current + delta + enabled.length) % enabled.length
    const target = enabled[next]
    if (target) onChange(target.id)
  }

  return (
    <div
      role="tablist"
      aria-label={ariaLabel}
      onKeyDown={handleKeyDown}
      className={cn('flex items-center gap-1 overflow-x-auto border-b border-border', className)}
    >
      {tabs.map(tab => {
        const isActive = tab.id === active
        return (
          <button
            key={tab.id}
            type="button"
            role="tab"
            aria-selected={isActive}
            tabIndex={isActive ? 0 : -1}
            disabled={tab.disabled}
            onClick={() => onChange(tab.id)}
            className={cn(
              'flex shrink-0 items-center gap-2 border-b-2 px-3 py-2 text-sm font-medium transition-colors',
              'focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-inset',
              'disabled:cursor-not-allowed disabled:opacity-50',
              isActive
                ? 'border-primary text-foreground'
                : 'border-transparent text-muted-foreground hover:border-border-strong hover:text-foreground',
            )}
          >
            {tab.label}
            {tab.badge}
          </button>
        )
      })}
    </div>
  )
}
