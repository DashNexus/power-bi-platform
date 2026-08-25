/**
 * Single source of truth for which SSO providers this deployment offers.
 *
 * **Microsoft Entra ID only.** The platform deploys onto Azure and signs in
 * against the tenant that already owns the Power BI workspaces, so a second
 * provider would be a second identity to reconcile against those workspaces.
 * This is a placeholder in one specific sense: the wiring is complete, but a
 * deployment ships with the three `AZURE_AD_*` variables unset, which leaves
 * password sign-in as the only route until the tenant is registered.
 *
 * Client secrets come from the environment, never from the API: the backend's
 * `GET /admin/auth-config/providers` masks `client_secret` by design (it returns
 * only `has_client_secret`), and it requires an admin session — so it can neither
 * supply a usable secret nor be reached from the unauthenticated login page.
 *
 * `lib/auth.ts` uses `getConfiguredProviders()` to register Auth.js providers,
 * and the login page uses `getLoginProviders()` to render one button per
 * provider. Both read the same env vars, so a provider can never appear as a
 * button without being wired up (or vice versa).
 *
 * Server-side callers only. This cannot carry an `import 'server-only'` marker
 * because `lib/auth.ts` pulls it into a graph the bundler also analyses for the
 * Edge middleware. Client components must import the `LoginProvider` *type*
 * alone (`import type`), which erases at compile time — never the functions,
 * which read secrets from `process.env`.
 */
export type ProviderId = 'microsoft'

export interface ConfiguredProvider {
  provider: ProviderId
  clientId: string
  clientSecret: string
  /** Scopes the issuer to a single Entra tenant. */
  tenantId?: string
}

/** Login-page-safe view: no secrets, just what to render. */
export interface LoginProvider {
  provider: ProviderId
  label: string
}

const LABELS: Record<ProviderId, string> = {
  microsoft: 'Sign in with Microsoft',
}

function env(name: string): string {
  return process.env[name]?.trim() ?? ''
}

/**
 * Return every provider with both a client ID and secret present.
 *
 * A provider with only one half configured is treated as unconfigured rather
 * than half-registered, which would otherwise fail at the redirect with an
 * opaque provider error.
 */
export function getConfiguredProviders(): ConfiguredProvider[] {
  const candidates: ConfiguredProvider[] = [
    {
      provider: 'microsoft',
      clientId: env('AZURE_AD_CLIENT_ID'),
      clientSecret: env('AZURE_AD_CLIENT_SECRET'),
      tenantId: env('AZURE_AD_TENANT_ID') || undefined,
    },
  ]
  return candidates.filter(c => c.clientId !== '' && c.clientSecret !== '')
}

export async function getLoginProviders(): Promise<LoginProvider[]> {
  return getConfiguredProviders().map(({ provider }) => ({
    provider,
    label: LABELS[provider],
  }))
}
