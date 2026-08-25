'use client'

/**
 * Multi-select for notification groups.
 *
 * Shows each group's destinations inline ("Slack ×2 · Email ×3") so an operator
 * can confirm where an alert lands without opening the groups admin, and links
 * straight there when nothing is configured yet.
 */
import Link from 'next/link'
import { ExternalLink, Users } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { cn } from '@/lib/utils'
import { describeChannels, type NotificationGroup } from './notificationTypes'

interface NotificationGroupPickerProps {
  label: string
  hint?: string
  groups: NotificationGroup[]
  selected: number[]
  onChange: (ids: number[]) => void
  /** Warn when alerts are enabled but nothing would receive them. */
  warnWhenEmpty?: boolean
  disabled?: boolean
}

export function NotificationGroupPicker({
  label,
  hint,
  groups,
  selected,
  onChange,
  warnWhenEmpty,
  disabled,
}: NotificationGroupPickerProps) {
  function toggle(id: number) {
    onChange(selected.includes(id) ? selected.filter(x => x !== id) : [...selected, id])
  }

  return (
    <div className="space-y-2">
      <div className="flex items-baseline justify-between gap-2">
        <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
          {label}
        </p>
        {selected.length > 0 && (
          <span className="text-xs text-muted-foreground">{selected.length} selected</span>
        )}
      </div>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}

      {groups.length === 0 ? (
        <div className="rounded-lg border border-dashed border-border px-3 py-4 text-center">
          <Users className="mx-auto mb-1.5 h-4 w-4 text-muted-foreground" aria-hidden />
          <p className="text-xs text-muted-foreground">No notification groups exist yet.</p>
          <Link
            href="/admin/notification-groups"
            className="mt-1 inline-flex items-center gap-1 text-xs font-medium text-primary hover:underline"
          >
            Create a group
            <ExternalLink className="h-3 w-3" aria-hidden />
          </Link>
        </div>
      ) : (
        <div className="space-y-0.5 rounded-lg border border-border p-1.5">
          {groups.map(g => {
            const checked = selected.includes(g.id)
            return (
              <label
                key={g.id}
                className={cn(
                  'flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors',
                  disabled ? 'opacity-60' : 'cursor-pointer hover:bg-accent',
                )}
              >
                <input
                  type="checkbox"
                  checked={checked}
                  disabled={disabled}
                  onChange={() => toggle(g.id)}
                  className="h-4 w-4 shrink-0 rounded border-border-strong text-primary focus:ring-2 focus:ring-ring"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm text-foreground">{g.name}</span>
                  <span className="block truncate text-xs text-muted-foreground">
                    {describeChannels(g)}
                  </span>
                </span>
              </label>
            )
          })}
        </div>
      )}

      {warnWhenEmpty && selected.length === 0 && groups.length > 0 && (
        <Badge tone="warning">Nothing selected — these alerts go nowhere</Badge>
      )}
    </div>
  )
}
