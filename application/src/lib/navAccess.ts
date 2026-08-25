/**
 * Pure navigation access helpers shared by the platform layout (server) and
 * PortalNav (client).
 *
 * Decides whether a navigation href should be shown to the current user. The
 * checks run in order and mirror the server-side route guards so a link appears
 * if and only if the user can actually reach its destination:
 *
 *   1. Admin routes (`/admin/*`) require the admin role.
 *   2. Feature-gated sections require the effective feature flag.
 *   3. Deep links to a specific resource require the user to have access to that
 *      resource — its id/slug must appear in the accessible set, which the API
 *      builds by filtering on each resource's required_role and permission grants.
 *
 * Contains no server-only imports so it can be bundled into client components.
 */
import { hasRole } from '@/lib/permissions'

/**
 * Identifiers of the resources the current user can access, gathered from the
 * user-facing listing endpoints (which are already permission-filtered).
 */
export interface ResourceAccess {
  dashboardIds: number[]
  pageSlugs: string[]
}

// Maps a URL path prefix to the feature key that controls the whole section.
const FEATURE_GATED_PREFIXES: Record<string, string> = {
  '/dashboard': 'dashboards',
  '/pages': 'custom_pages',
  '/data-dicts': 'governance',
  '/pipelines': 'pipelines',
  '/exports': 'exports',
}

function matchesPrefix(href: string, prefix: string): boolean {
  return href === prefix || href.startsWith(`${prefix}/`) || href.startsWith(`${prefix}?`)
}

/** Extract the first path segment after `${prefix}/`, e.g. /dashboard/12 -> "12". */
function resourceIdFromHref(href: string, prefix: string): string | null {
  const path = href.split(/[?#]/)[0]
  if (!path.startsWith(`${prefix}/`)) return null
  const segment = path.slice(prefix.length + 1).split('/')[0]
  return segment || null
}

/**
 * Return true if the nav href should be visible to the user.
 *
 * @param href - The nav link target. External (http/https) links are always shown.
 * @param features - The user's effective feature flags (post role-visibility).
 * @param role - The user's role.
 * @param access - Accessible resource identifiers, or null to skip per-resource
 *   filtering (e.g. for admins, or when the nav has no deep links).
 */
export function isHrefAccessible(
  href: string | undefined,
  features: Record<string, boolean>,
  role: string | undefined,
  access: ResourceAccess | null,
): boolean {
  if (!href) return true

  // External links are outside the app's access model.
  if (/^https?:\/\//i.test(href)) return true

  // 1. Admin routes are admin-only, regardless of feature flags.
  if (href === '/admin' || href.startsWith('/admin/') || href.startsWith('/admin?')) {
    return hasRole(role, 'admin')
  }

  // Admins bypass feature and per-resource filtering.
  if (hasRole(role, 'admin')) return true

  // 2. Feature-gated sections.
  for (const [prefix, key] of Object.entries(FEATURE_GATED_PREFIXES)) {
    if (!matchesPrefix(href, prefix)) continue
    if (!features[key]) return false

    // 3. Deep link to a specific resource — verify access to that resource.
    const id = access ? resourceIdFromHref(href, prefix) : null
    if (access && id) {
      switch (prefix) {
        case '/dashboard':
          return access.dashboardIds.includes(Number(id))
        case '/pages':
          return access.pageSlugs.includes(id)
      }
    }
    return true
  }

  return true
}
