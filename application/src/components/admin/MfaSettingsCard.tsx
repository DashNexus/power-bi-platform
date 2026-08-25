'use client'

/**
 * Organisation-level MFA settings card.
 *
 * Controls whether TOTP two-factor authentication is required for all users.
 * When required, users who log in without TOTP set up are redirected to
 * /settings/security to complete enrolment before accessing the platform.
 */
import { useState } from 'react'
import * as Switch from '@radix-ui/react-switch'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

export interface MfaSettings {
  totp_enabled: boolean
  totp_required: boolean
  email_otp_enabled: boolean
  grace_period_days: number
}

interface MfaSettingsCardProps {
  initialSettings: MfaSettings
  onSave: (data: Partial<MfaSettings>) => Promise<void>
}

export function MfaSettingsCard({ initialSettings, onSave }: MfaSettingsCardProps) {
  const [totpRequired, setTotpRequired] = useState(initialSettings.totp_required)
  const [gracePeriod, setGracePeriod] = useState(String(initialSettings.grace_period_days))
  const [saving, setSaving] = useState(false)

  async function handleRequiredToggle(checked: boolean) {
    setSaving(true)
    try {
      await onSave({ totp_required: checked })
      setTotpRequired(checked)
      toast.success(
        checked
          ? 'Two-factor authentication is now required for all users.'
          : 'Two-factor authentication requirement removed.',
      )
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update MFA settings.')
    } finally {
      setSaving(false)
    }
  }

  async function handleGracePeriodSave() {
    setSaving(true)
    try {
      await onSave({ grace_period_days: parseInt(gracePeriod, 10) || 0 })
      toast.success('Grace period updated.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to update grace period.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="px-5 py-4 border-b border-border">
        <div className="flex items-center gap-3">
          <span className="text-xl">🔐</span>
          <div>
            <p className="text-sm font-medium text-foreground">Organisation MFA Policy</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              Controls two-factor authentication requirements for all users
            </p>
          </div>
        </div>
      </div>

      <div className="px-5 py-5 space-y-5">
        {/* Require TOTP */}
        <div className="flex items-start justify-between gap-6">
          <div>
            <p className="text-sm font-medium text-foreground">Require two-factor authentication</p>
            <p className="text-sm text-muted-foreground mt-0.5">
              Users without 2FA set up will be redirected to the security settings page
              immediately after login until they complete enrolment.
            </p>
          </div>
          <Switch.Root
            checked={totpRequired}
            disabled={saving}
            onCheckedChange={handleRequiredToggle}
            aria-label={totpRequired ? 'Disable required 2FA' : 'Enable required 2FA'}
            className={cn(
              'relative flex-shrink-0 inline-flex h-5 w-9 rounded-full border-2 border-transparent',
              'transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
              totpRequired ? 'bg-primary' : 'bg-secondary',
              saving ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
            )}
          >
            <Switch.Thumb
              className={cn(
                'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-card shadow',
                'transition duration-200 ease-in-out',
                totpRequired ? 'translate-x-4' : 'translate-x-0',
              )}
            />
          </Switch.Root>
        </div>

        {/* Grace period */}
        {totpRequired && (
          <div className="rounded-lg bg-muted border border-border p-4 space-y-3">
            <div>
              <label className="block text-sm font-medium text-foreground mb-1">
                Grace period (days)
              </label>
              <p className="text-xs text-muted-foreground mb-2">
                Allow existing users this many days to set up 2FA before being locked out.
                Set to 0 for immediate enforcement.
              </p>
              <div className="flex items-center gap-3">
                <input
                  type="number"
                  value={gracePeriod}
                  onChange={e => setGracePeriod(e.target.value)}
                  min={0}
                  max={90}
                  className="w-24 rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
                <button
                  type="button"
                  onClick={handleGracePeriodSave}
                  disabled={saving}
                  className="rounded-lg border border-border px-3 py-2 text-sm font-medium text-muted-foreground hover:bg-card transition-colors disabled:opacity-50"
                >
                  {saving ? 'Saving…' : 'Save'}
                </button>
              </div>
            </div>
          </div>
        )}

        {totpRequired && (
          <p className="text-xs text-warning-strong bg-warning-subtle border border-amber-100 rounded-lg px-3 py-2">
            <strong>Note:</strong> Users will not be logged out of existing sessions immediately.
            The redirect applies on their next login when the session expires or they sign out.
          </p>
        )}
      </div>
    </div>
  )
}
