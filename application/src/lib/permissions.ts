/**
 * Role-based access control helpers.
 *
 * Role hierarchy (highest to lowest): superadmin > admin > analyst > viewer
 */

export type Role = 'superadmin' | 'admin' | 'analyst' | 'viewer'

const ROLE_LEVEL: Record<Role, number> = {
  superadmin: 4,
  admin: 3,
  analyst: 2,
  viewer: 1,
}

/** Return true if the user's role is at least the required role. */
export function hasRole(userRole: string | undefined, requiredRole: Role): boolean {
  if (!userRole) return false
  return (ROLE_LEVEL[userRole as Role] ?? 0) >= ROLE_LEVEL[requiredRole]
}

/** Return true if the user has at least one of the given roles. */
export function hasAnyRole(userRole: string | undefined, ...roles: Role[]): boolean {
  return roles.some(r => hasRole(userRole, r))
}
