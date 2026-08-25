/**
 * Status pill.
 *
 * `tone` maps to the semantic colour tokens rather than a raw palette, so a
 * "failed" badge is the same red in every table across the app. `StatusBadge`
 * layers on the shared vocabulary for pipeline/export/job states so each page
 * stops inventing its own mapping.
 */
import { cva, type VariantProps } from 'class-variance-authority'
import { cn } from '@/lib/utils'

const badgeVariants = cva(
  'inline-flex shrink-0 items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium [&_svg]:size-3',
  {
    variants: {
      tone: {
        neutral: 'border-border bg-muted text-muted-foreground',
        primary: 'border-transparent bg-primary-subtle text-info-strong',
        success: 'border-transparent bg-success-subtle text-success-strong',
        warning: 'border-transparent bg-warning-subtle text-warning-strong',
        danger: 'border-transparent bg-destructive-subtle text-destructive-strong',
        info: 'border-transparent bg-info-subtle text-info-strong',
        assistant: 'border-assistant-border bg-assistant-subtle text-assistant',
        outline: 'border-border-strong bg-transparent text-foreground',
      },
    },
    defaultVariants: { tone: 'neutral' },
  },
)

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, tone, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ tone }), className)} {...props} />
}

type Tone = NonNullable<BadgeProps['tone']>

/**
 * Canonical state → tone mapping.
 *
 * Keys are lowercased on lookup, so both Prefect's `COMPLETED` and the API's
 * `completed` resolve to the same tone.
 */
const STATUS_TONES: Record<string, Tone> = {
  // terminal success
  completed: 'success',
  complete: 'success',
  success: 'success',
  succeeded: 'success',
  active: 'success',
  enabled: 'success',
  healthy: 'success',
  ready: 'success',
  passed: 'success',
  online: 'success',
  running: 'info',
  // in flight
  pending: 'warning',
  queued: 'warning',
  scheduled: 'warning',
  in_progress: 'info',
  processing: 'info',
  // attention
  warning: 'warning',
  warn: 'warning',
  stale: 'warning',
  degraded: 'warning',
  paused: 'warning',
  // terminal failure
  failed: 'danger',
  failure: 'danger',
  error: 'danger',
  crashed: 'danger',
  cancelled: 'danger',
  canceled: 'danger',
  revoked: 'danger',
  expired: 'danger',
  // inert
  disabled: 'neutral',
  inactive: 'neutral',
  stopped: 'neutral',
  draft: 'neutral',
  unknown: 'neutral',
  offline: 'neutral',
}

export function statusTone(status: string | null | undefined): Tone {
  if (!status) return 'neutral'
  return STATUS_TONES[status.toLowerCase().replace(/[\s-]+/g, '_')] ?? 'neutral'
}

export interface StatusBadgeProps extends Omit<BadgeProps, 'tone' | 'children'> {
  status: string | null | undefined
  /** Override the rendered text; defaults to a humanised form of `status`. */
  label?: string
}

export function StatusBadge({ status, label, ...props }: StatusBadgeProps) {
  const text = label ?? (status ? status.replace(/_/g, ' ') : 'unknown')
  return (
    <Badge tone={statusTone(status)} className="capitalize" {...props}>
      {text}
    </Badge>
  )
}
