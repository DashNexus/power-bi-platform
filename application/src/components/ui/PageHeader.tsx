/**
 * Page and section headings.
 *
 * Standardises the title / description / actions row that every route was
 * re-implementing, including the eleven different `<h1>` class strings that had
 * accumulated. Always render exactly one `PageHeader` per route so the page has
 * exactly one `<h1>`.
 */
import { cn } from '@/lib/utils'

interface PageHeaderProps {
  title: string
  description?: string
  /** Buttons or filters aligned to the trailing edge of the title row. */
  actions?: React.ReactNode
  /** Breadcrumbs or a back link rendered above the title. */
  eyebrow?: React.ReactNode
  className?: string
}

export function PageHeader({ title, description, actions, eyebrow, className }: PageHeaderProps) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-4', className)}>
      <div className="min-w-0">
        {eyebrow && <div className="mb-1 text-xs text-muted-foreground">{eyebrow}</div>}
        <h1 className="truncate text-2xl font-semibold tracking-tight text-foreground">{title}</h1>
        {description && <p className="mt-1 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 flex-wrap items-center gap-2">{actions}</div>}
    </div>
  )
}

interface SectionHeaderProps {
  title: string
  description?: string
  actions?: React.ReactNode
  className?: string
}

/** Sub-heading inside a page. Renders an `<h2>`. */
export function SectionHeader({ title, description, actions, className }: SectionHeaderProps) {
  return (
    <div className={cn('flex flex-wrap items-start justify-between gap-3', className)}>
      <div className="min-w-0">
        <h2 className="text-base font-semibold text-foreground">{title}</h2>
        {description && <p className="mt-0.5 text-sm text-muted-foreground">{description}</p>}
      </div>
      {actions && <div className="flex shrink-0 items-center gap-2">{actions}</div>}
    </div>
  )
}
