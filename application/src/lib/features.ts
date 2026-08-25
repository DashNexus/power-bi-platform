/**
 * Feature flag helpers.
 *
 * isEnabled() checks in this order:
 *   1. FEATURE_* server-side environment variable (always takes precedence)
 *   2. API call to GET /admin/features (per-org DB value)
 *   3. false (default when the flag is absent)
 *
 * Results from the API are cached per request via React's cache() so that
 * multiple isEnabled() calls in the same render do not make multiple HTTP
 * requests. The env var check is always re-evaluated at call time.
 *
 * Environment variable naming: FEATURE_<KEY_UPPER> where dots become
 * underscores. Examples:
 *   chat              → FEATURE_CHAT
 *   exports           → FEATURE_EXPORTS
 *   embed.powerbi     → FEATURE_EMBED_POWERBI
 *   embed.streamlit   → FEATURE_EMBED_STREAMLIT
 */
import { cache } from 'react'
import { apiFetch } from '@/lib/api'

export type FeatureKey =
  | 'dashboards'
  | 'embed.powerbi'
  | 'embed.tableau'
  | 'embed.custom_react'
  | 'embed.streamlit'
  | 'chat'
  | 'exports'
  | 'custom_pages'
  | 'timelines'
  | 'pipelines'
  | 'prefect_monitor'
  | 'pipelines.prefect'
  | 'pipelines.adf'
  | 'lineage'
  | 'data_lineage'
  | 'governance'
  | 'backups'
  | 'retention'
  | 'project_planning'
  | 'project_management'
  | 'time_tracking'
  | 'billing'
  | 'tickets'

interface FeatureFlagResponse {
  feature_key: FeatureKey
  enabled: boolean
  env_override: boolean
}

/**
 * Convert a feature key to its FEATURE_* environment variable name.
 *
 * @example keyToEnvVar('embed.powerbi') === 'FEATURE_EMBED_POWERBI'
 */
export function keyToEnvVar(key: FeatureKey): string {
  return `FEATURE_${key.toUpperCase().replace(/\./g, '_')}`
}

/**
 * Return the env var override for a feature key, or null if not set.
 *
 * Only available in server-side code — process.env is not available in
 * browser bundles. Client components always go through the API.
 */
export function getEnvOverride(key: FeatureKey): boolean | null {
  const raw = process.env[keyToEnvVar(key)]
  if (raw === undefined || raw === null || raw === '') return null
  return raw.toLowerCase() === 'true' || raw === '1' || raw.toLowerCase() === 'yes'
}

const fetchFeatureFlags = cache(async (): Promise<FeatureFlagResponse[]> => {
  try {
    // /portal/features is accessible to all authenticated users; /admin/features
    // is admin-only and would return 403 for non-admin roles, hiding all features.
    return await apiFetch<FeatureFlagResponse[]>('/portal/features')
  } catch {
    return []
  }
})

/** Return true if a feature is enabled for the current org. */
export async function isEnabled(key: FeatureKey): Promise<boolean> {
  // Env var wins — consistent with the API behaviour.
  const envOverride = getEnvOverride(key)
  if (envOverride !== null) return envOverride

  const flags = await fetchFeatureFlags()
  return flags.find(f => f.feature_key === key)?.enabled ?? false
}

/** Return all feature flags as a record (effective values including env overrides). */
export async function getAllFeatures(): Promise<Record<FeatureKey, boolean>> {
  const flags = await fetchFeatureFlags()
  const result = {} as Record<FeatureKey, boolean>
  flags.forEach(f => {
    const envOverride = getEnvOverride(f.feature_key)
    result[f.feature_key] = envOverride !== null ? envOverride : f.enabled
  })
  return result
}
