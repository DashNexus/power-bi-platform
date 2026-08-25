/**
 * Auth provider configuration page.
 *
 * Displays identity providers, SSO enforcement, pipeline connectors, and the
 * org-level MFA policy. Power BI credentials belong to a BI connection, so they
 * are configured on /admin/bi-connections instead.
 */
import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { apiFetch } from '@/lib/api'
import { hasRole } from '@/lib/permissions'
import type { MfaSettings } from '@/components/admin/MfaSettingsCard'
import type { SsoSettings } from '@/components/admin/SsoSettingsCard'
import { AuthConfigClient } from './AuthConfigClient'

export const metadata = {
  title: 'Auth Configuration',
}

interface ProviderConfig {
  id: number
  provider: string
  enabled: boolean
  client_id: string
  has_client_secret: boolean
  config: Record<string, string> | null
}

async function getProviders(): Promise<ProviderConfig[]> {
  try {
    return await apiFetch<ProviderConfig[]>('/admin/auth-config/providers')
  } catch {
    return []
  }
}

async function getMfaSettings(): Promise<MfaSettings> {
  try {
    return await apiFetch<MfaSettings>('/admin/auth-config/mfa')
  } catch {
    return { totp_enabled: true, totp_required: false, email_otp_enabled: false, grace_period_days: 0 }
  }
}

async function getSsoSettings(): Promise<SsoSettings> {
  try {
    return await apiFetch<SsoSettings>('/admin/auth-config/sso')
  } catch {
    return { require_sso: false, allowed_providers: [] }
  }
}

export default async function AuthConfigPage() {
  const session = await auth()

  if (!session?.user) {
    redirect('/login')
  }

  if (!hasRole(session.user.role, 'admin')) {
    redirect('/dashboard')
  }

  const [providers, mfaSettings, ssoSettings] = await Promise.all([
    getProviders(),
    getMfaSettings(),
    getSsoSettings(),
  ])

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">Auth Configuration</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Configure identity providers, data pipeline connectors, and security policy.
        </p>
      </div>

      <AuthConfigClient
        initialProviders={providers}
        initialMfaSettings={mfaSettings}
        initialSsoSettings={ssoSettings}
        accessToken={session.user.access_token}
      />
    </div>
  )
}
