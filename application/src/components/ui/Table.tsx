/**
 * Table primitives.
 *
 * Thirty-five files hand-rolled `<table>` markup with slightly different
 * padding, border, and header casing. These wrappers keep the semantics native
 * (so `DataTable` and one-off tables can share them) while fixing the chrome.
 *
 * `TableContainer` supplies the horizontal scroll that wide tables need — the
 * page body must never scroll sideways.
 */
import { cn } from '@/lib/utils'

export function TableContainer({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn('w-full overflow-x-auto rounded-xl border border-border bg-card', className)}
      {...props}
    />
  )
}

export function Table({ className, ...props }: React.TableHTMLAttributes<HTMLTableElement>) {
  return <table className={cn('w-full caption-bottom text-sm', className)} {...props} />
}

export function TableHead({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <thead className={cn('border-b border-border bg-muted/60', className)} {...props} />
}

export function TableBody({ className, ...props }: React.HTMLAttributes<HTMLTableSectionElement>) {
  return <tbody className={cn('divide-y divide-border', className)} {...props} />
}

export interface TableRowProps extends React.HTMLAttributes<HTMLTableRowElement> {
  /** Adds a hover tint — use for rows that are clickable or reveal actions. */
  interactive?: boolean
}

export function TableRow({ className, interactive, ...props }: TableRowProps) {
  return (
    <tr
      className={cn('transition-colors', interactive && 'cursor-pointer hover:bg-accent/60', className)}
      {...props}
    />
  )
}

export interface TableHeaderCellProps extends React.ThHTMLAttributes<HTMLTableCellElement> {
  align?: 'left' | 'right' | 'center'
}

export function TableHeaderCell({ className, align = 'left', ...props }: TableHeaderCellProps) {
  return (
    <th
      scope="col"
      className={cn(
        'whitespace-nowrap px-4 py-2.5 text-xs font-semibold uppercase tracking-wide text-muted-foreground',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        align === 'left' && 'text-left',
        className,
      )}
      {...props}
    />
  )
}

export interface TableCellProps extends React.TdHTMLAttributes<HTMLTableCellElement> {
  align?: 'left' | 'right' | 'center'
  /** De-emphasise secondary columns (timestamps, counts, ids). */
  muted?: boolean
}

export function TableCell({ className, align = 'left', muted, ...props }: TableCellProps) {
  return (
    <td
      className={cn(
        'px-4 py-2.5 text-sm',
        muted ? 'text-muted-foreground' : 'text-foreground',
        align === 'right' && 'text-right',
        align === 'center' && 'text-center',
        className,
      )}
      {...props}
    />
  )
}

interface TableEmptyProps {
  colSpan: number
  children: React.ReactNode
}

/** Full-width message row for an empty table body. */
export function TableEmpty({ colSpan, children }: TableEmptyProps) {
  return (
    <tr>
      <td colSpan={colSpan} className="px-4 py-10 text-center text-sm text-muted-foreground">
        {children}
      </td>
    </tr>
  )
}
