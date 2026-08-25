/**
 * Cached portal settings fetch shared across the platform layout and per-feature
 * route guards.
 *
 * React.cache() ensures multiple calls within the same request (e.g. the
 * platform layout + a nested feature layout) make only one API round-trip.
 */
import { cache } from 'react'
import { apiFetch } from '@/lib/api'
import type { ResourceAccess } from '@/lib/navAccess'

/**
 * One entry in the admin-authored navigation: a link, or a dropdown of links.
 *
 * Mirrors `NavItem` in `api/app/schemas/nav_config.py`, which is what validates
 * an href before it is ever stored. Widening this without widening that lets a
 * shape through that the API will reject on the next save.
 */
export interface NavConfigItem {
  type: 'link' | 'dropdown'
  label: string
  href?: string
  items?: Array<{ label: string; href: string }>
}

export interface PortalSettings {
  app_name: string
  logo_url: string | null
  /** null or empty means every user sees the default navigation. */
  nav_config: NavConfigItem[] | null
}

export const getPortalSettings = cache(async (): Promise<PortalSettings> => {
  try {
    return await apiFetch<PortalSettings>('/portal/settings')
  } catch {
    // Falling back to the defaults rather than an empty shell: a settings call
    // that fails must not take the whole navigation with it.
    return { app_name: 'Power BI Platform', logo_url: null, nav_config: null }
  }
})

/**
 * Fetch the identifiers of resources the current user can access.
 *
 * Reads the user-facing listing endpoints, which the API already filters by
 * each resource's required_role and permission grants. Used to hide nav links
 * that deep-link to a specific dashboard or page the user cannot open. Each
 * endpoint is caught individually so one failure fails closed (empty list) for
 * its resource type rather than dropping the whole nav.
 */
export const getAccessibleResources = cache(async (): Promise<ResourceAccess> => {
  const [dashboards, pages] = await Promise.all([
    apiFetch<Array<{ id: number }>>('/dashboards').catch(() => [] as Array<{ id: number }>),
    apiFetch<Array<{ slug: string }>>('/pages').catch(() => [] as Array<{ slug: string }>),
  ])
  return {
    dashboardIds: dashboards.map(d => d.id),
    pageSlugs: pages.map(p => p.slug),
  }
})

/**
 * Return the effective feature set for a role.
 *
 * Feature visibility is driven by role permissions and computed authoritatively
 * by the API (`GET /portal/features` returns effective flags for the current
 * user). This is a passthrough kept so call sites — the platform layout and the
 * route guards — read the same way whichever side decides; the `role` argument
 * is deliberately unused.
 */
export function computeEffectiveFeatures(
  role: string,
  rawFeatures: Record<string, boolean>,
): Record<string, boolean> {
  void role
  return rawFeatures
}
