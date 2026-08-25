'use client'

/**
 * TOTP enrollment and management UI.
 *
 * When TOTP is disabled: shows a QR code from the API and a code input to
 * confirm activation. When TOTP is enabled: shows a disable button with
 * confirmation. The QR code is rendered from the base64 image returned by
 * the API so no external dependencies are needed.
 */
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { createClientFetch } from '@/lib/api'
import { cn } from '@/lib/utils'

interface TotpEnrollmentProps {
  initialEnabled: boolean
  qrCodeBase64: string | null
  provisioningUri: string | null
  userEmail: string
}

export function TotpEnrollment({
  initialEnabled,
  qrCodeBase64,
  provisioningUri,
  userEmail: _userEmail,
}: TotpEnrollmentProps) {
  const { data: session, update } = useSession()
  const router = useRouter()
  const apiFetch = createClientFetch(session?.user?.access_token)
  const mfaSetupRequired = session?.user?.mfa_setup_required ?? false

  const [enabled, setEnabled] = useState(initialEnabled)
  const [qrBase64, setQrBase64] = useState(qrCodeBase64)
  const [uri, setUri] = useState(provisioningUri)
  const [code, setCode] = useState('')
  const [isVerifying, setIsVerifying] = useState(false)
  const [isDisabling, setIsDisabling] = useState(false)
  const [showDisableConfirm, setShowDisableConfirm] = useState(false)

  async function handleSetup() {
    try {
      const data = await apiFetch<{ qr_code_base64: string; provisioning_uri: string }>(
        '/auth/totp/setup',
        { method: 'POST' },
      )
      setQrBase64(data.qr_code_base64)
      setUri(data.provisioning_uri)
    } catch {
      toast.error('Failed to generate QR code. Please try again.')
    }
  }

  async function handleEnable() {
    if (code.length !== 6) {
      toast.error('Enter the 6-digit code from your authenticator app.')
      return
    }

    setIsVerifying(true)
    try {
      await apiFetch('/auth/totp/enable', {
        method: 'POST',
        body: JSON.stringify({ code }),
      })
      setEnabled(true)
      setCode('')
      setQrBase64(null)
      setUri(null)
      toast.success('Two-factor authentication enabled.')
      // Clear mfa_setup_required from the session so middleware stops redirecting
      await update({ totp_enabled: true })
      if (mfaSetupRequired) router.replace('/home')
    } catch {
      toast.error('Incorrect code. Please try again.')
    } finally {
      setIsVerifying(false)
    }
  }

  async function handleDisable() {
    setIsDisabling(true)
    try {
      await apiFetch('/auth/totp/disable', { method: 'POST' })
      setEnabled(false)
      setShowDisableConfirm(false)
      toast.success('Two-factor authentication disabled.')
    } catch {
      toast.error('Failed to disable two-factor authentication. Please try again.')
    } finally {
      setIsDisabling(false)
    }
  }

  if (enabled) {
    return (
      <div>
        <div className="flex items-center gap-3 mb-4">
          <span className="inline-flex items-center rounded-full bg-success-subtle px-2.5 py-0.5 text-xs font-medium text-success-strong">
            Enabled
          </span>
          <p className="text-sm text-muted-foreground">
            Your account is protected with two-factor authentication.
          </p>
        </div>

        {!showDisableConfirm ? (
          <button
            type="button"
            onClick={() => setShowDisableConfirm(true)}
            className="rounded-lg border border-destructive/40 bg-card px-4 py-2 text-sm font-medium text-destructive-strong hover:bg-destructive-subtle transition-colors"
          >
            Disable Two-factor Authentication
          </button>
        ) : (
          <div className="rounded-lg border border-destructive-subtle bg-destructive-subtle p-4 space-y-3">
            <p className="text-sm text-destructive-strong">
              Disabling two-factor authentication reduces your account security.
              Are you sure?
            </p>
            <div className="flex gap-2">
              <button
                type="button"
                onClick={handleDisable}
                disabled={isDisabling}
                className={cn(
                  'rounded-lg bg-destructive px-3 py-1.5 text-sm font-medium text-white',
                  'hover:bg-destructive/90 transition-colors',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                )}
              >
                {isDisabling ? 'Disabling...' : 'Disable'}
              </button>
              <button
                type="button"
                onClick={() => setShowDisableConfirm(false)}
                className="rounded-lg border border-border-strong bg-card px-3 py-1.5 text-sm font-medium text-muted-foreground hover:bg-accent transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}
      </div>
    )
  }

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-3">
        <span className="inline-flex items-center rounded-full bg-muted px-2.5 py-0.5 text-xs font-medium text-muted-foreground">
          Not enabled
        </span>
        <p className="text-sm text-muted-foreground">
          Add an extra layer of security to your account.
        </p>
      </div>

      {!qrBase64 ? (
        <button
          type="button"
          onClick={handleSetup}
          className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover transition-colors"
        >
          Set Up Two-factor Authentication
        </button>
      ) : (
        <div className="space-y-4">
          <div>
            <p className="text-sm text-muted-foreground mb-3">
              Scan this QR code with your authenticator app (Google Authenticator,
              Authy, or 1Password), then enter the 6-digit code to confirm.
            </p>

            {/* QR code image */}
            <div className="inline-block rounded-xl border border-border p-3 bg-card">
              {/* eslint-disable-next-line @next/next/no-img-element -- inline data URI; next/image cannot optimise it */}
              <img
                src={`data:image/png;base64,${qrBase64}`}
                alt="TOTP QR code"
                width={180}
                height={180}
                className="block"
              />
            </div>
          </div>

          {/* Manual entry URI */}
          {uri && (
            <details className="text-xs text-muted-foreground">
              <summary className="cursor-pointer hover:text-foreground">
                Can&apos;t scan? Enter the code manually
              </summary>
              <code className="mt-2 block break-all rounded bg-muted border border-border p-2 text-foreground">
                {uri}
              </code>
            </details>
          )}

          {/* Verification input */}
          <div>
            <label htmlFor="totp-verify" className="block text-sm font-medium text-foreground">
              Verification code
            </label>
            <div className="mt-1 flex gap-2">
              <input
                id="totp-verify"
                type="text"
                inputMode="numeric"
                maxLength={6}
                placeholder="000000"
                value={code}
                onChange={e => setCode(e.target.value.replace(/\D/g, '').slice(0, 6))}
                className={cn(
                  'block w-36 rounded-lg border border-border-strong px-3 py-2 text-center',
                  'font-mono text-lg tracking-widest shadow-sm',
                  'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
                )}
              />
              <button
                type="button"
                onClick={handleEnable}
                disabled={isVerifying || code.length !== 6}
                className={cn(
                  'rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground',
                  'hover:bg-primary-hover transition-colors',
                  'disabled:opacity-50 disabled:cursor-not-allowed',
                )}
              >
                {isVerifying ? 'Verifying...' : 'Enable'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
