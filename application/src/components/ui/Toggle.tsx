'use client'

/**
 * Switch primitive.
 *
 * Every feature that needed a toggle previously re-declared the same Radix
 * root/thumb class pair (MfaSettingsCard, PipelineNotificationsTab,
 * NotificationPreferences), so they drifted apart.
 * `ToggleRow` adds the bordered label+switch line those screens all build.
 */
import * as Switch from '@radix-ui/react-switch'
import { cn } from '@/lib/utils'

interface ToggleProps {
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  /** Required unless the toggle is labelled by a visible `ToggleRow` title. */
  ariaLabel?: string
  disabled?: boolean
  id?: string
}

export function Toggle({ checked, onCheckedChange, ariaLabel, disabled, id }: ToggleProps) {
  return (
    <Switch.Root
      id={id}
      checked={checked}
      disabled={disabled}
      onCheckedChange={onCheckedChange}
      aria-label={ariaLabel}
      className={cn(
        'relative inline-flex h-5 w-9 shrink-0 rounded-full border-2 border-transparent',
        'transition-colors focus-visible:outline-none focus-visible:ring-2',
        'focus-visible:ring-ring focus-visible:ring-offset-2 focus-visible:ring-offset-background',
        checked ? 'bg-primary' : 'bg-border-strong',
        disabled ? 'cursor-not-allowed opacity-50' : 'cursor-pointer',
      )}
    >
      <Switch.Thumb
        className={cn(
          'pointer-events-none inline-block h-4 w-4 rounded-full bg-card shadow transition-transform',
          checked ? 'translate-x-4' : 'translate-x-0',
        )}
      />
    </Switch.Root>
  )
}

interface ToggleRowProps {
  label: string
  hint?: string
  checked: boolean
  onCheckedChange: (checked: boolean) => void
  disabled?: boolean
}

/** Bordered row with a label, optional hint, and a trailing switch. */
export function ToggleRow({ label, hint, checked, onCheckedChange, disabled }: ToggleRowProps) {
  return (
    <label
      className={cn(
        'flex items-center justify-between gap-3 rounded-lg border border-border px-3 py-2.5',
        disabled ? 'opacity-60' : 'cursor-pointer hover:bg-accent/50',
      )}
    >
      <span className="min-w-0">
        <span className="block text-sm text-foreground">{label}</span>
        {hint && <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>}
      </span>
      <Toggle
        checked={checked}
        onCheckedChange={onCheckedChange}
        disabled={disabled}
        ariaLabel={label}
      />
    </label>
  )
}
