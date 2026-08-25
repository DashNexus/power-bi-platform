// @vitest-environment jsdom
/**
 * Tests for PortalNav's navigation rendering.
 *
 * The interesting behaviour is not which links exist but which ones a given
 * user is shown: an admin can put any dashboard in the navigation, and the nav
 * must not advertise one the viewer cannot open. That filtering is display-only
 * — the route still enforces access — but a nav full of links that 404 is how a
 * user learns to distrust the whole thing.
 */
import '@testing-library/jest-dom/vitest'
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import type { Session } from 'next-auth'
import { PortalNav } from '@/components/layout/PortalNav'
import type { NavConfigItem } from '@/lib/portal'
import type { ResourceAccess } from '@/lib/navAccess'

// jsdom implements neither, and ScrollableNav observes its own width.
vi.stubGlobal(
  'ResizeObserver',
  class {
    observe() {}
    unobserve() {}
    disconnect() {}
  },
)
Element.prototype.scrollBy = () => {}

vi.mock('next-auth/react', () => ({ signOut: vi.fn() }))
vi.mock('next-themes', () => ({ useTheme: () => ({ theme: 'light', setTheme: vi.fn() }) }))

const ALL_FEATURES = {
  dashboards: true,
  custom_pages: true,
  governance: true,
  pipelines: true,
  exports: true,
}

function sessionFor(role: string): Session {
  return {
    user: { name: 'Test', email: 't@example.com', role, access_token: 'x' },
    expires: '2099-01-01',
  } as unknown as Session
}

const ACCESS: ResourceAccess = { dashboardIds: [1], pageSlugs: ['allowed'] }

function renderNav(
  navConfig: NavConfigItem[] | null,
  {
    role = 'viewer',
    features = ALL_FEATURES,
    access = ACCESS,
  }: { role?: string; features?: Record<string, boolean>; access?: ResourceAccess | null } = {},
) {
  return render(
    <PortalNav
      session={sessionFor(role)}
      orgSettings={{ app_name: 'Test', logo_url: null, nav_config: navConfig }}
      features={features}
      navConfig={navConfig}
      resourceAccess={access}
    />,
  )
}

/** Hrefs in the nav bar itself, excluding the brand and the avatar menu. */
function navHrefs(): string[] {
  const nav = document.querySelector('nav')
  return Array.from(nav?.querySelectorAll('a') ?? []).map(a => a.getAttribute('href') ?? '')
}

describe('PortalNav — default navigation', () => {
  it('renders the default links when nothing is configured', () => {
    renderNav(null)

    expect(navHrefs()).toContain('/home')
    expect(navHrefs()).toContain('/dashboard')
  })

  it('renders the defaults for an empty configuration', () => {
    // An admin who removed every item wants the defaults back, not a bare bar.
    renderNav([])

    expect(navHrefs()).toContain('/home')
  })

  it('leaves out a section whose feature is off', () => {
    renderNav(null, { features: { ...ALL_FEATURES, exports: false } })

    expect(navHrefs()).not.toContain('/exports')
  })
})

describe('PortalNav — configured navigation', () => {
  it('replaces the defaults with the configured links', () => {
    renderNav([{ type: 'link', label: 'Reports', href: '/exports' }])

    expect(screen.getByRole('link', { name: 'Reports' })).toHaveAttribute('href', '/exports')
    // The defaults are replaced, not appended — otherwise configuring a nav
    // could only ever make it longer.
    expect(navHrefs()).not.toContain('/dashboard')
  })

  it('keeps the order the admin set', () => {
    renderNav([
      { type: 'link', label: 'Second', href: '/exports' },
      { type: 'link', label: 'First', href: '/pages' },
    ])

    expect(navHrefs()).toEqual(['/exports', '/pages'])
  })

  it('shows a deep link to a dashboard the user can open', () => {
    renderNav([{ type: 'link', label: 'Mine', href: '/dashboard/1' }])

    expect(navHrefs()).toContain('/dashboard/1')
  })

  it('hides a deep link to a dashboard the user cannot open', () => {
    // The admin may link any dashboard; the nav must not advertise one this
    // viewer has no grant for.
    renderNav([{ type: 'link', label: 'Not mine', href: '/dashboard/99' }])

    expect(navHrefs()).not.toContain('/dashboard/99')
    expect(screen.queryByRole('link', { name: 'Not mine' })).not.toBeInTheDocument()
  })

  it('hides a link whose whole feature is off for the user', () => {
    renderNav([{ type: 'link', label: 'Exports', href: '/exports' }], {
      features: { ...ALL_FEATURES, exports: false },
    })

    expect(navHrefs()).not.toContain('/exports')
  })

  it('hides an admin route from a non-admin', () => {
    renderNav([{ type: 'link', label: 'Users', href: '/admin/users' }])

    expect(navHrefs()).not.toContain('/admin/users')
  })

  it('shows an admin route to an admin', () => {
    renderNav([{ type: 'link', label: 'Users', href: '/admin/users' }], { role: 'admin' })

    expect(navHrefs()).toContain('/admin/users')
  })

  it('shows an external link, which is outside the access model', () => {
    renderNav([{ type: 'link', label: 'Docs', href: 'https://example.com/docs' }])

    expect(navHrefs()).toContain('https://example.com/docs')
  })

  it('skips a link item that somehow has no target', () => {
    // The API rejects this shape, but the column is JSON an older build could
    // have written — rendering it would produce an anchor to the current page.
    renderNav([{ type: 'link', label: 'Broken' }])

    expect(screen.queryByRole('link', { name: 'Broken' })).not.toBeInTheDocument()
  })
})

describe('PortalNav — dropdowns', () => {
  it('renders a dropdown trigger when at least one child is visible', () => {
    renderNav([
      {
        type: 'dropdown',
        label: 'Reports',
        items: [
          { label: 'Mine', href: '/dashboard/1' },
          { label: 'Not mine', href: '/dashboard/99' },
        ],
      },
    ])

    expect(screen.getByRole('button', { name: /Reports/ })).toBeInTheDocument()
  })

  it('hides a dropdown whose every child is hidden', () => {
    // It would open onto an empty menu, which reads as broken rather than as
    // "nothing here for you".
    renderNav([
      {
        type: 'dropdown',
        label: 'Reports',
        items: [{ label: 'Not mine', href: '/dashboard/99' }],
      },
    ])

    expect(screen.queryByRole('button', { name: /Reports/ })).not.toBeInTheDocument()
  })

  it('hides a dropdown with no children at all', () => {
    renderNav([{ type: 'dropdown', label: 'Empty', items: [] }])

    expect(screen.queryByRole('button', { name: /Empty/ })).not.toBeInTheDocument()
  })
})

describe('PortalNav — admins', () => {
  it('shows an admin every configured deep link without a resource list', () => {
    // The platform layout passes null for an admin; isHrefAccessible treats
    // that as "skip per-resource filtering", which must not hide everything.
    renderNav([{ type: 'link', label: 'Any', href: '/dashboard/12345' }], {
      role: 'admin',
      access: null,
    })

    expect(navHrefs()).toContain('/dashboard/12345')
  })
})
