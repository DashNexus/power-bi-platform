'use client'

/**
 * SSO enforcement settings card.
 *
 * Controls whether users must authenticate via a specific identity provider
 * (SSO only) and which providers are allowed. Settings are stored in the
 * org settings config via PUT /admin/auth-config/sso.
 */
import { useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import * as Switch from '@radix-ui/react-switch'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'

export interface SsoSettings {
  require_sso: boolean
  allowed_providers: string[]
}

interface SsoSettingsCardProps {
  initialSettings: SsoSettings
  onSave: (data: Partial<SsoSettings>) => Promise<void>
  configuredProviders: string[]
}

const PROVIDER_LABELS: Record<string, string> = {
  microsoft: 'Microsoft Entra ID',
}

export function SsoSettingsCard({
  initialSettings,
  onSave,
  configuredProviders,
}: SsoSettingsCardProps) {
  const [expanded, setExpanded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [requireSso, setRequireSso] = useState(initialSettings.require_sso)
  const [allowedProviders, setAllowedProviders] = useState<string[]>(
    initialSettings.allowed_providers,
  )

  function toggleProvider(key: string) {
    setAllowedProviders(prev =>
      prev.includes(key) ? prev.filter(p => p !== key) : [...prev, key],
    )
  }

  async function handleSave() {
    setSaving(true)
    try {
      await onSave({ require_sso: requireSso, allowed_providers: allowedProviders })
      setExpanded(false)
      toast.success('SSO settings saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save SSO settings.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="text-xl">🔑</span>
          <div>
            <p className="text-sm font-medium text-foreground">SSO Enforcement</p>
            <p className="text-xs text-muted-foreground mt-0.5">
              {requireSso
                ? `SSO required — ${allowedProviders.length === 0 ? 'any configured provider' : allowedProviders.map(p => PROVIDER_LABELS[p] ?? p).join(', ')}`
                : 'Password login allowed alongside SSO'}
            </p>
          </div>
        </div>
        <button
          onClick={() => setExpanded(e => !e)}
          className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          aria-label={expanded ? 'Collapse' : 'Expand'}
        >
          {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
        </button>
      </div>

      {expanded && (
        <div className="border-t border-border px-5 py-5 space-y-5">
          {/* Require SSO toggle */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-foreground">Require SSO login</p>
              <p className="text-xs text-muted-foreground mt-0.5">
                When enabled, users cannot log in with email and password — they must use one of
                the configured identity providers below. Existing password-only accounts will be
                prompted to link an SSO identity on next login.
              </p>
            </div>
            <Switch.Root
              checked={requireSso}
              onCheckedChange={setRequireSso}
              aria-label={requireSso ? 'Disable SSO requirement' : 'Enable SSO requirement'}
              className={cn(
                'relative mt-0.5 inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent cursor-pointer',
                'transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                requireSso ? 'bg-primary' : 'bg-secondary',
              )}
            >
              <Switch.Thumb
                className={cn(
                  'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-card shadow',
                  'transition duration-200 ease-in-out',
                  requireSso ? 'translate-x-4' : 'translate-x-0',
                )}
              />
            </Switch.Root>
          </div>

          {/* Allowed providers */}
          {requireSso && (
            <div>
              <p className="text-sm font-medium text-foreground mb-1">
                Allowed identity providers
                <span className="ml-2 text-xs font-normal text-muted-foreground">
                  (leave all unchecked to allow any configured provider)
                </span>
              </p>
              {configuredProviders.length === 0 ? (
                <p className="text-xs text-warning-strong rounded border border-warning-subtle bg-warning-subtle px-3 py-2">
                  No identity providers are configured yet. Go to{' '}
                  <strong>Identity providers</strong> above to add Microsoft, Google, GitHub, or
                  custom OIDC first.
                </p>
              ) : (
                <div className="space-y-2 rounded-lg border border-border p-3">
                  {configuredProviders.map(key => (
                    <label key={key} className="flex items-center gap-2 cursor-pointer">
                      <input
                        type="checkbox"
                        checked={allowedProviders.includes(key)}
                        onChange={() => toggleProvider(key)}
                        className="h-4 w-4 rounded border-border-strong text-primary focus:ring-ring"
                      />
                      <span className="text-sm text-foreground">
                        {PROVIDER_LABELS[key] ?? key}
                      </span>
                    </label>
                  ))}
                </div>
              )}
            </div>
          )}

          <div className="flex justify-end pt-1">
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
