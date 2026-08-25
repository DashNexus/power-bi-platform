'use client'

/**
 * Client wrapper for auth provider configuration.
 *
 * Manages the Microsoft Entra ID provider card, the Azure Data Factory
 * connector, and org-level MFA/SSO policy.
 *
 * Power BI credentials are not configured here. They live on a BI connection
 * (/admin/bi-connections), of which an org may have several; a single org-wide
 * service principal on this page could only ever describe one of them.
 *
 * Microsoft is the only identity provider this build offers. The card is wired
 * end to end but ships unconfigured — it is the placeholder the real tenant
 * details drop into. Registering a second provider means adding it here *and*
 * in `lib/authProviders.ts`, which is what the login page reads.
 */
import { useState } from 'react'
import { createClientFetch } from '@/lib/api'
import { AuthProviderCard } from '@/components/admin/AuthProviderCard'
import type { AuthProviderConfig } from '@/components/admin/AuthProviderCard'
import {
  PipelineConnectorCard,
  type PipelineConnectorType,
  type PipelineConnectorConfig,
} from '@/components/admin/PipelineConnectorCard'
import { MfaSettingsCard, type MfaSettings } from '@/components/admin/MfaSettingsCard'
import { SsoSettingsCard, type SsoSettings } from '@/components/admin/SsoSettingsCard'

type OAuthProviderKey = 'microsoft'

interface OAuthProviderRecord extends AuthProviderConfig {
  id: number
  provider: OAuthProviderKey
}

interface RawProviderRecord {
  id: number
  provider: string
  enabled: boolean
  client_id: string
  has_client_secret: boolean
  config: Record<string, string> | null
}

interface AuthConfigClientProps {
  initialProviders: RawProviderRecord[]
  initialMfaSettings: MfaSettings
  initialSsoSettings: SsoSettings
  accessToken: string
}

const OAUTH_PROVIDERS: { key: OAuthProviderKey; displayName: string }[] = [
  { key: 'microsoft', displayName: 'Microsoft Entra ID (Azure AD)' },
]

const PIPELINE_CONNECTORS: { key: PipelineConnectorType; displayName: string }[] = [
  { key: 'azure_data_factory', displayName: 'Azure Data Factory' },
]

function toOAuthRecord(raw: RawProviderRecord): OAuthProviderRecord {
  return {
    id: raw.id,
    provider: raw.provider as OAuthProviderKey,
    enabled: raw.enabled,
    client_id: raw.client_id,
    client_secret: raw.has_client_secret ? '••••••••' : '',
    tenant_id: raw.config?.['tenant_id'],
  }
}

export function AuthConfigClient({
  initialProviders,
  initialMfaSettings,
  initialSsoSettings,
  accessToken,
}: AuthConfigClientProps) {
  const [providers, setProviders] = useState<RawProviderRecord[]>(initialProviders)
  const [mfaSettings, setMfaSettings] = useState<MfaSettings>(initialMfaSettings)
  const [ssoSettings, setSsoSettings] = useState<SsoSettings>(initialSsoSettings)
  const apiFetch = createClientFetch(accessToken)

  // --- OAuth providers ---

  function getOAuthConfig(key: OAuthProviderKey): OAuthProviderRecord | null {
    const raw = providers.find(p => p.provider === key)
    return raw ? toOAuthRecord(raw) : null
  }

  function updateProvider(provider: string, updated: Partial<RawProviderRecord>) {
    setProviders(prev =>
      prev.map(p => (p.provider === provider ? { ...p, ...updated } : p)),
    )
  }

  function handleOAuthSave(key: OAuthProviderKey) {
    return async (data: Record<string, string>) => {
      const existing = providers.find(p => p.provider === key)
      const body = JSON.stringify({ provider: key, ...data })
      if (existing?.id) {
        const saved = await apiFetch<RawProviderRecord>(
          `/admin/auth-config/providers/${existing.id}`,
          { method: 'PUT', body },
        )
        setProviders(prev => prev.map(p => (p.id === saved.id ? saved : p)))
      } else {
        const saved = await apiFetch<RawProviderRecord>('/admin/auth-config/providers', {
          method: 'POST',
          body,
        })
        setProviders(prev => [...prev, saved])
      }
    }
  }

  function handleOAuthDelete(key: OAuthProviderKey) {
    return async () => {
      const existing = providers.find(p => p.provider === key)
      if (!existing?.id) return
      await apiFetch(`/admin/auth-config/providers/${existing.id}`, { method: 'DELETE' })
      setProviders(prev => prev.filter(p => p.provider !== key))
    }
  }

  function handleOAuthToggle(key: OAuthProviderKey) {
    return async (enabled: boolean) => {
      const existing = providers.find(p => p.provider === key)
      if (!existing?.id) return
      await apiFetch<RawProviderRecord>(`/admin/auth-config/providers/${existing.id}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled }),
      })
      updateProvider(key, { enabled })
    }
  }

  // --- Pipeline connectors ---

  function getPipelineConfig(key: PipelineConnectorType): PipelineConnectorConfig | null {
    const raw = providers.find(p => p.provider === key)
    if (!raw) return null
    return {
      id: raw.id,
      enabled: raw.enabled,
      client_id: raw.client_id,
      has_client_secret: raw.has_client_secret,
      config: raw.config,
    }
  }

  function handlePipelineSave(key: PipelineConnectorType) {
    return async (data: Record<string, unknown>) => {
      const existing = providers.find(p => p.provider === key)
      const body = JSON.stringify({ provider: key, ...data })
      if (existing?.id) {
        const saved = await apiFetch<RawProviderRecord>(
          `/admin/auth-config/providers/${existing.id}`,
          { method: 'PUT', body },
        )
        setProviders(prev => prev.map(p => (p.id === saved.id ? saved : p)))
      } else {
        const saved = await apiFetch<RawProviderRecord>('/admin/auth-config/providers', {
          method: 'POST',
          body,
        })
        setProviders(prev => [...prev, saved])
      }
    }
  }

  function handlePipelineDelete(key: PipelineConnectorType) {
    return async () => {
      const existing = providers.find(p => p.provider === key)
      if (!existing?.id) return
      await apiFetch(`/admin/auth-config/providers/${existing.id}`, { method: 'DELETE' })
      setProviders(prev => prev.filter(p => p.provider !== key))
    }
  }

  function handlePipelineToggle(key: PipelineConnectorType) {
    return async (enabled: boolean) => {
      const existing = providers.find(p => p.provider === key)
      if (!existing?.id) return
      await apiFetch<RawProviderRecord>(`/admin/auth-config/providers/${existing.id}`, {
        method: 'PUT',
        body: JSON.stringify({ enabled }),
      })
      updateProvider(key, { enabled })
    }
  }

  function handlePipelineTestConnection(key: PipelineConnectorType) {
    if (key !== 'azure_data_factory') return undefined
    return () =>
      apiFetch<{ ok: boolean; error?: string; pipeline_count?: number }>('/pipelines/adf/test', {
        method: 'POST',
      })
  }

  // --- MFA settings ---

  async function handleMfaSave(data: Partial<MfaSettings>) {
    const updated = await apiFetch<MfaSettings>('/admin/auth-config/mfa', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    setMfaSettings(updated)
  }

  // --- SSO enforcement ---

  async function handleSsoSave(data: Partial<SsoSettings>) {
    const updated = await apiFetch<SsoSettings>('/admin/auth-config/sso', {
      method: 'PUT',
      body: JSON.stringify(data),
    })
    setSsoSettings(updated)
  }

  const configuredOAuthProviders = providers
    .filter(p => p.provider === 'microsoft' && p.enabled)
    .map(p => p.provider)

  return (
    <div className="space-y-8">
      {/* MFA policy */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Security policy
        </h2>
        <div className="space-y-4">
          <MfaSettingsCard initialSettings={mfaSettings} onSave={handleMfaSave} />
          <SsoSettingsCard
            initialSettings={ssoSettings}
            onSave={handleSsoSave}
            configuredProviders={configuredOAuthProviders}
          />
        </div>
      </section>

      {/* OAuth / OIDC providers */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Identity providers
        </h2>
        <div className="space-y-4">
          {OAUTH_PROVIDERS.map(({ key, displayName }) => (
            <AuthProviderCard
              key={key}
              provider={key}
              displayName={displayName}
              config={getOAuthConfig(key)}
              onSave={handleOAuthSave(key)}
              onDelete={handleOAuthDelete(key)}
              onToggle={handleOAuthToggle(key)}
            />
          ))}
        </div>
      </section>

      {/* Data pipeline connections */}
      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wider text-muted-foreground">
          Data pipeline connections
        </h2>
        <div className="space-y-4">
          {PIPELINE_CONNECTORS.map(({ key, displayName }) => (
            <PipelineConnectorCard
              key={key}
              connector={key}
              displayName={displayName}
              config={getPipelineConfig(key)}
              onSave={handlePipelineSave(key)}
              onDelete={handlePipelineDelete(key)}
              onToggle={handlePipelineToggle(key)}
              onTestConnection={handlePipelineTestConnection(key)}
            />
          ))}
        </div>
      </section>
    </div>
  )
}
