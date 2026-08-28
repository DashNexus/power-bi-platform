/**
 * Unit tests for the middleware admin role guard and MFA-enrolment redirect.
 *
 * next-auth is mocked so that auth() is an identity wrapper — the exported
 * default from middleware.ts is therefore the raw inner callback, letting us
 * call it directly with mock request objects.
 *
 * NextResponse.redirect is captured via vi.hoisted() to avoid the
 * temporal-dead-zone error that would arise from referencing a const inside a
 * hoisted vi.mock() factory.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

// vi.hoisted() runs before everything else, including vi.mock() factories.
const { mockRedirect } = vi.hoisted(() => ({
  mockRedirect: vi.fn(),
}))

vi.mock('next-auth', () => ({
  default: () => ({
    auth: (handler: (req: unknown) => unknown) => handler,
  }),
}))

vi.mock('next/server', () => ({
  NextResponse: {
    redirect: mockRedirect,
  },
}))

vi.mock('@/lib/auth', () => ({
  authConfig: { providers: [], callbacks: {}, pages: {} },
  auth: vi.fn(),
  handlers: {},
  signIn: vi.fn(),
  signOut: vi.fn(),
}))

import handler, { config } from '@/middleware'

// ─── helpers ──────────────────────────────────────────────────────────────────

interface MockUser {
  role?: string
  mfa_setup_required?: boolean
}

interface MockRequest {
  auth: { user: MockUser } | null
  nextUrl: { pathname: string }
  url: string
}

/**
 * The next-auth mock reduces auth() to an identity wrapper, so the default
 * export is the bare callback. Its published signature is
 * (NextRequest, NextFetchEvent), which a plain object literal cannot satisfy —
 * hence the single narrow cast here instead of one per call site.
 */
const middleware = handler as unknown as (req: MockRequest) => unknown

function makeReq(pathname: string, user?: MockUser): MockRequest {
  return {
    auth: user ? { user } : null,
    nextUrl: { pathname },
    url: `http://localhost:3000${pathname}`,
  }
}

function redirectedTo(): string {
  return (mockRedirect.mock.calls[0][0] as URL).pathname
}

// ─── tests ─────────────────────────────────────────────────────────────────────

describe('middleware admin guard', () => {
  beforeEach(() => {
    mockRedirect.mockClear()
    mockRedirect.mockReturnValue({ type: 'redirect' })
  })

  it('redirects viewer accessing an /admin route to /home', () => {
    middleware(makeReq('/admin/users', { role: 'viewer' }))

    expect(mockRedirect).toHaveBeenCalledOnce()
    expect(redirectedTo()).toBe('/home')
  })

  it('redirects analyst accessing an /admin route to /home', () => {
    middleware(makeReq('/admin/roles', { role: 'analyst' }))

    expect(mockRedirect).toHaveBeenCalledOnce()
    expect(redirectedTo()).toBe('/home')
  })

  it('does not redirect admin accessing an /admin route', () => {
    middleware(makeReq('/admin/users', { role: 'admin' }))

    expect(mockRedirect).not.toHaveBeenCalled()
  })

  it('does not redirect superadmin accessing an /admin route', () => {
    middleware(makeReq('/admin/dashboards', { role: 'superadmin' }))

    expect(mockRedirect).not.toHaveBeenCalled()
  })

  it('does not redirect viewer on non-admin routes', () => {
    middleware(makeReq('/dashboard', { role: 'viewer' }))
    middleware(makeReq('/chat', { role: 'viewer' }))
    middleware(makeReq('/exports', { role: 'analyst' }))

    expect(mockRedirect).not.toHaveBeenCalled()
  })

  it('does not redirect on /admin when the user is unauthenticated (Auth.js handles that)', () => {
    middleware(makeReq('/admin/users'))

    expect(mockRedirect).not.toHaveBeenCalled()
  })
})

describe('middleware matcher', () => {
  // Auth.js redirects an unauthenticated request to /login before the
  // authorized() callback runs, so a page reachable without an account has to
  // be excluded here — allowing it in the callback is too late. An invitee
  // following their link has no session to be redirected back from.
  const matcher = new RegExp(`^${config.matcher[0]}$`)

  it.each(['/accept-invite', '/login', '/forgot-password', '/reset-password'])(
    'does not run on %s',
    (pathname: string) => {
      expect(matcher.test(pathname)).toBe(false)
    },
  )

  it.each(['/home', '/admin/users', '/dashboard/4'])('runs on %s', (pathname: string) => {
    expect(matcher.test(pathname)).toBe(true)
  })
})

describe('middleware MFA enrolment guard', () => {
  beforeEach(() => {
    mockRedirect.mockClear()
    mockRedirect.mockReturnValue({ type: 'redirect' })
  })

  it('redirects a user owing MFA enrolment to /settings/security', () => {
    middleware(makeReq('/home', { role: 'analyst', mfa_setup_required: true }))

    expect(mockRedirect).toHaveBeenCalledOnce()
    expect(redirectedTo()).toBe('/settings/security')
  })

  it('lets a user owing MFA enrolment reach the enrolment page itself', () => {
    middleware(makeReq('/settings/security', { role: 'analyst', mfa_setup_required: true }))

    expect(mockRedirect).not.toHaveBeenCalled()
  })

  it('exempts the sign-in and legacy MFA routes so enrolment cannot deadlock', () => {
    middleware(makeReq('/login', { role: 'analyst', mfa_setup_required: true }))
    middleware(makeReq('/mfa', { role: 'analyst', mfa_setup_required: true }))

    expect(mockRedirect).not.toHaveBeenCalled()
  })

  it('takes precedence over the admin guard for an admin owing enrolment', () => {
    middleware(makeReq('/admin/users', { role: 'admin', mfa_setup_required: true }))

    expect(mockRedirect).toHaveBeenCalledOnce()
    expect(redirectedTo()).toBe('/settings/security')
  })

  it('does not redirect a user who has completed enrolment', () => {
    middleware(makeReq('/home', { role: 'analyst', mfa_setup_required: false }))

    expect(mockRedirect).not.toHaveBeenCalled()
  })
})
