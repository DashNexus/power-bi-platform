import { describe, it, expect } from 'vitest'
import { isHrefAccessible, type ResourceAccess } from '@/lib/navAccess'

const ALL_FEATURES: Record<string, boolean> = {
  dashboards: true,
  custom_pages: true,
  governance: true,
  pipelines: true,
  exports: true,
}

const ACCESS: ResourceAccess = {
  dashboardIds: [1, 2],
  pageSlugs: ['about'],
}

describe('isHrefAccessible — admin routes', () => {
  it('shows /admin routes only to admins', () => {
    expect(isHrefAccessible('/admin/users', ALL_FEATURES, 'admin', null)).toBe(true)
    expect(isHrefAccessible('/admin/users', ALL_FEATURES, 'superadmin', null)).toBe(true)
    expect(isHrefAccessible('/admin/users', ALL_FEATURES, 'analyst', null)).toBe(false)
    expect(isHrefAccessible('/admin/users', ALL_FEATURES, 'viewer', null)).toBe(false)
  })

  it('hides an admin deep link from non-admins', () => {
    expect(isHrefAccessible('/admin/dashboards?view=10', ALL_FEATURES, 'viewer', ACCESS)).toBe(
      false,
    )
  })
})

describe('isHrefAccessible — feature gating', () => {
  it('hides a section whose feature flag is off', () => {
    const features = { ...ALL_FEATURES, exports: false }
    expect(isHrefAccessible('/exports', features, 'viewer', null)).toBe(false)
  })

  it('shows a section whose feature flag is on', () => {
    expect(isHrefAccessible('/exports', ALL_FEATURES, 'viewer', null)).toBe(true)
  })

  it('maps /data-dicts to governance and /pipelines to pipelines', () => {
    expect(
      isHrefAccessible('/data-dicts', { ...ALL_FEATURES, governance: false }, 'viewer', null),
    ).toBe(false)
    expect(
      isHrefAccessible('/pipelines', { ...ALL_FEATURES, pipelines: false }, 'viewer', null),
    ).toBe(false)
  })

  it('admins bypass feature gating', () => {
    const features = { ...ALL_FEATURES, exports: false }
    expect(isHrefAccessible('/exports', features, 'admin', null)).toBe(true)
  })
})

describe('isHrefAccessible — per-resource access', () => {
  it('shows a deep link when the resource is in the accessible set', () => {
    expect(isHrefAccessible('/dashboard/1', ALL_FEATURES, 'viewer', ACCESS)).toBe(true)
    expect(isHrefAccessible('/pages/about', ALL_FEATURES, 'viewer', ACCESS)).toBe(true)
  })

  it('hides a deep link when the resource is not accessible', () => {
    expect(isHrefAccessible('/dashboard/9', ALL_FEATURES, 'viewer', ACCESS)).toBe(false)
    expect(isHrefAccessible('/pages/secret', ALL_FEATURES, 'viewer', ACCESS)).toBe(false)
  })

  it('does not filter section-listing links by resource', () => {
    expect(isHrefAccessible('/dashboard', ALL_FEATURES, 'viewer', ACCESS)).toBe(true)
  })

  it('skips per-resource filtering when access is null', () => {
    expect(isHrefAccessible('/dashboard/9', ALL_FEATURES, 'viewer', null)).toBe(true)
  })

  it('honours query strings on deep links', () => {
    expect(isHrefAccessible('/dashboard/2?tab=sales', ALL_FEATURES, 'viewer', ACCESS)).toBe(true)
    expect(isHrefAccessible('/dashboard/9?tab=sales', ALL_FEATURES, 'viewer', ACCESS)).toBe(false)
  })
})

describe('isHrefAccessible — misc', () => {
  it('allows external links', () => {
    expect(isHrefAccessible('https://example.com', {}, 'viewer', null)).toBe(true)
  })

  it('allows ungated internal routes', () => {
    expect(isHrefAccessible('/home', {}, 'viewer', null)).toBe(true)
    expect(isHrefAccessible('/settings', {}, 'viewer', null)).toBe(true)
  })

  it('allows an undefined href (dropdown parent)', () => {
    expect(isHrefAccessible(undefined, {}, 'viewer', null)).toBe(true)
  })
})
