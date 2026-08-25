import { auth } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import { TotpEnrollment } from '@/components/settings/TotpEnrollment'

export const metadata = {
  title: 'Security',
}

interface TotpStatus {
  enabled: boolean
  provisioning_uri?: string
  qr_code_base64?: string
}

async function getTotpStatus(): Promise<TotpStatus> {
  try {
    return await apiFetch<TotpStatus>('/auth/totp/status')
  } catch {
    return { enabled: false }
  }
}

export default async function SecurityPage() {
  const session = await auth()
  const totpStatus = await getTotpStatus()
  const mfaSetupRequired = (session?.user as { mfa_setup_required?: boolean } | undefined)?.mfa_setup_required ?? false

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">Security</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Manage two-factor authentication for your account.
        </p>
      </div>

      {mfaSetupRequired && (
        <div className="mb-6 rounded-lg border border-warning-subtle bg-warning-subtle p-4">
          <p className="text-sm font-medium text-warning-strong">
            Two-factor authentication is required by your organisation.
          </p>
          <p className="mt-1 text-sm text-warning-strong">
            Set up 2FA below to continue accessing the platform.
          </p>
        </div>
      )}

      <div className="rounded-xl border border-border bg-card p-6 shadow-sm">
        <h2 className="text-sm font-semibold text-foreground mb-4">
          Two-factor authentication (TOTP)
        </h2>
        <TotpEnrollment
          initialEnabled={totpStatus.enabled}
          qrCodeBase64={totpStatus.qr_code_base64 ?? null}
          provisioningUri={totpStatus.provisioning_uri ?? null}
          userEmail={session?.user?.email ?? ''}
        />
      </div>
    </div>
  )
}
