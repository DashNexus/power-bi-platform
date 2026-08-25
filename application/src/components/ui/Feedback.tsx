/**
 * Inline feedback and loading affordances: Alert, Skeleton, Spinner, LoadingRows.
 *
 * Toasts (sonner) cover transient feedback; `Alert` covers persistent in-page
 * messages such as a form-level error or a dry-run warning.
 */
import { cva, type VariantProps } from 'class-variance-authority'
import { AlertTriangle, CheckCircle2, Info, Loader2, XCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

const alertVariants = cva('flex gap-3 rounded-lg border px-3.5 py-3 text-sm', {
  variants: {
    tone: {
      info: 'border-info-subtle bg-info-subtle text-foreground',
      success: 'border-success-subtle bg-success-subtle text-foreground',
      warning: 'border-warning-subtle bg-warning-subtle text-foreground',
      danger: 'border-destructive-subtle bg-destructive-subtle text-foreground',
    },
  },
  defaultVariants: { tone: 'info' },
})

const ALERT_ICONS = {
  info: Info,
  success: CheckCircle2,
  warning: AlertTriangle,
  danger: XCircle,
} as const

const ALERT_ICON_TONES = {
  info: 'text-info-strong',
  success: 'text-success-strong',
  warning: 'text-warning-strong',
  danger: 'text-destructive-strong',
} as const

export interface AlertProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof alertVariants> {
  title?: string
}

export function Alert({ className, tone = 'info', title, children, ...props }: AlertProps) {
  const key = tone ?? 'info'
  const Icon = ALERT_ICONS[key]
  return (
    <div
      role={key === 'danger' ? 'alert' : 'status'}
      className={cn(alertVariants({ tone }), className)}
      {...props}
    >
      <Icon className={cn('mt-0.5 h-4 w-4 shrink-0', ALERT_ICON_TONES[key])} aria-hidden />
      <div className="min-w-0 flex-1 space-y-0.5">
        {title && <p className="font-medium text-foreground">{title}</p>}
        {children && <div className="text-muted-foreground">{children}</div>}
      </div>
    </div>
  )
}

export function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn('animate-pulse rounded-md bg-muted', className)} {...props} />
}

export interface SpinnerProps extends React.SVGProps<SVGSVGElement> {
  label?: string
}

export function Spinner({ className, label = 'Loading', ...props }: SpinnerProps) {
  return (
    <Loader2
      role="status"
      aria-label={label}
      className={cn('h-4 w-4 animate-spin text-muted-foreground', className)}
      {...props}
    />
  )
}

interface LoadingRowsProps {
  rows?: number
  className?: string
}

/** Skeleton stand-in for a list or table body while data is in flight. */
export function LoadingRows({ rows = 4, className }: LoadingRowsProps) {
  return (
    <div className={cn('space-y-2', className)} role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-11 w-full" />
      ))}
    </div>
  )
}
