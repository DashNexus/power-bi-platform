/**
 * Empty and error placeholders for lists, tables, and panels.
 *
 * BRAND.md requires every empty state to say what is empty, why it might be
 * empty, and what to do next — so `description` is mandatory and `action` is
 * strongly encouraged.
 */
import type { LucideIcon } from 'lucide-react'
import { AlertTriangle, Inbox } from 'lucide-react'
import { cn } from '@/lib/utils'

interface EmptyStateProps {
  /** What is empty. Sentence case, no trailing period. */
  title: string
  /** Why it is empty and what the user can do next. */
  description: string
  icon?: LucideIcon
  action?: React.ReactNode
  className?: string
}

export function EmptyState({ title, description, icon: Icon = Inbox, action, className }: EmptyStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-xl border border-dashed border-border px-6 py-12 text-center',
        className,
      )}
    >
      <div className="flex h-10 w-10 items-center justify-center rounded-full bg-muted">
        <Icon className="h-5 w-5 text-muted-foreground" aria-hidden />
      </div>
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  )
}

interface ErrorStateProps {
  title?: string
  description: string
  action?: React.ReactNode
  className?: string
}

/** Failure counterpart to EmptyState — same footprint, danger tone. */
export function ErrorState({
  title = 'Could not load this content',
  description,
  action,
  className,
}: ErrorStateProps) {
  return (
    <div
      className={cn(
        'flex flex-col items-center justify-center gap-3 rounded-xl border border-destructive-subtle bg-destructive-subtle/50 px-6 py-10 text-center',
        className,
      )}
      role="alert"
    >
      <AlertTriangle className="h-6 w-6 text-destructive-strong" aria-hidden />
      <div className="space-y-1">
        <p className="text-sm font-medium text-foreground">{title}</p>
        <p className="mx-auto max-w-md text-sm text-muted-foreground">{description}</p>
      </div>
      {action}
    </div>
  )
}
