'use client'

/**
 * MFA policy configuration page.
 *
 * Fetches the current MFA settings on mount and lets admins toggle TOTP
 * enforcement, set the grace period, and optionally enable email OTP. Changes
 * are written with a single PUT on form submission.
 */
import { useEffect, useState } from 'react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import * as Switch from '@radix-ui/react-switch'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { createClientFetch } from '@/lib/api'
import { cn } from '@/lib/utils'

const mfaSchema = z.object({
  require_totp: z.boolean(),
  grace_period_days: z
    .number({ invalid_type_error: 'Grace period must be a number' })
    .int('Grace period must be a whole number')
    .min(0, 'Grace period cannot be negative')
    .max(365, 'Grace period cannot exceed 365 days'),
  email_otp_enabled: z.boolean(),
})

type MfaFormValues = z.infer<typeof mfaSchema>

interface MfaSettings {
  require_totp: boolean
  grace_period_days: number
  email_otp_enabled: boolean
}

/**
 * Client component that fetches and saves the organisation-wide MFA policy.
 */
export default function MfaPage() {
  const { data: session } = useSession()
  const [loading, setLoading] = useState(true)
  const [fetchError, setFetchError] = useState<string | null>(null)

  const {
    register,
    handleSubmit,
    setValue,
    watch,
    formState: { errors, isSubmitting },
  } = useForm<MfaFormValues>({
    resolver: zodResolver(mfaSchema),
    defaultValues: {
      require_totp: false,
      grace_period_days: 0,
      email_otp_enabled: false,
    },
  })

  const requireTotp = watch('require_totp')
  const emailOtpEnabled = watch('email_otp_enabled')

  useEffect(() => {
    if (!session?.user?.access_token) return

    const apiFetch = createClientFetch(session.user.access_token)

    apiFetch<MfaSettings>('/admin/auth-config/mfa')
      .then(data => {
        setValue('require_totp', data.require_totp)
        setValue('grace_period_days', data.grace_period_days)
        setValue('email_otp_enabled', data.email_otp_enabled)
      })
      .catch(err => {
        const msg = err instanceof Error ? err.message : 'Failed to load MFA settings'
        setFetchError(msg)
      })
      .finally(() => setLoading(false))
  }, [session?.user?.access_token, setValue])

  async function onSubmit(values: MfaFormValues) {
    if (!session?.user?.access_token) return
    const apiFetch = createClientFetch(session.user.access_token)
    try {
      await apiFetch('/admin/auth-config/mfa', {
        method: 'PUT',
        body: JSON.stringify(values),
      })
      toast.success('MFA settings saved.')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      toast.error(`Failed to save MFA settings: ${msg}`)
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <p className="text-sm text-muted-foreground">Loading MFA settings…</p>
      </div>
    )
  }

  if (fetchError) {
    return (
      <div className="rounded-xl border border-destructive-subtle bg-destructive-subtle px-5 py-4">
        <p className="text-sm text-destructive-strong">
          Failed to load MFA settings: {fetchError}. Try refreshing the page.
        </p>
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">MFA Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Configure multi-factor authentication requirements for all users.
        </p>
      </div>

      <div>
        <form
          onSubmit={handleSubmit(onSubmit)}
          noValidate
          className="space-y-6 rounded-xl border border-border bg-card p-6 shadow-sm"
        >
          {/* Require TOTP */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-foreground">Require TOTP</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Users must enrol a TOTP authenticator app before accessing the platform.
              </p>
            </div>
            <Switch.Root
              id="require-totp"
              checked={requireTotp}
              onCheckedChange={checked => setValue('require_totp', checked)}
              className={cn(
                'relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent',
                'transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                requireTotp ? 'bg-primary' : 'bg-secondary',
              )}
            >
              <Switch.Thumb
                className={cn(
                  'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-card shadow',
                  'transition duration-200 ease-in-out',
                  requireTotp ? 'translate-x-4' : 'translate-x-0',
                )}
              />
            </Switch.Root>
          </div>

          {/* Grace period */}
          <div className="space-y-1">
            <label
              htmlFor="grace-period"
              className="block text-sm font-medium text-foreground"
            >
              Grace period (days)
            </label>
            <p className="text-xs text-muted-foreground">
              Number of days after account creation before TOTP is required.
              Set to 0 to enforce immediately.
            </p>
            <input
              id="grace-period"
              type="number"
              min={0}
              max={365}
              {...register('grace_period_days', { valueAsNumber: true })}
              disabled={!requireTotp}
              className={cn(
                'block w-32 rounded-lg border px-3 py-2 text-sm shadow-sm',
                'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
                errors.grace_period_days
                  ? 'border-destructive/40 bg-destructive-subtle'
                  : 'border-border-strong bg-card',
                !requireTotp && 'opacity-50 cursor-not-allowed bg-muted',
              )}
            />
            {errors.grace_period_days && (
              <p className="text-xs text-destructive-strong">{errors.grace_period_days.message}</p>
            )}
          </div>

          {/* Email OTP */}
          <div className="flex items-start justify-between gap-4">
            <div>
              <p className="text-sm font-medium text-foreground">Email OTP</p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                Send a one-time code via email as an alternative to TOTP. Requires email
                notifications to be enabled.
              </p>
            </div>
            <Switch.Root
              id="email-otp"
              checked={emailOtpEnabled}
              onCheckedChange={checked => setValue('email_otp_enabled', checked)}
              className={cn(
                'relative inline-flex h-5 w-9 flex-shrink-0 cursor-pointer rounded-full border-2 border-transparent',
                'transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                emailOtpEnabled ? 'bg-primary' : 'bg-secondary',
              )}
            >
              <Switch.Thumb
                className={cn(
                  'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-card shadow',
                  'transition duration-200 ease-in-out',
                  emailOtpEnabled ? 'translate-x-4' : 'translate-x-0',
                )}
              />
            </Switch.Root>
          </div>

          <div className="border-t border-border pt-4">
            <button
              type="submit"
              disabled={isSubmitting}
              className={cn(
                'inline-flex items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground',
                'hover:bg-primary-hover transition-colors focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                isSubmitting && 'opacity-60 cursor-not-allowed',
              )}
            >
              {isSubmitting ? 'Saving…' : 'Save MFA Settings'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}
