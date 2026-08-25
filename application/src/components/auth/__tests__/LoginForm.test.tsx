// @vitest-environment jsdom
/**
 * Tests for LoginForm.
 *
 * Covers field validation, the credential pre-check branches (bad password vs.
 * TOTP required), the inline TOTP step, OAuth button rendering, and the
 * guarantee that credentials never reach web storage.
 *
 * `fetch` is mocked in every test: the component pre-checks credentials against
 * the API before calling signIn(), so leaving fetch real made the suite depend
 * on a live backend at localhost:8000.
 */
import '@testing-library/jest-dom/vitest'
import type { AppRouterInstance } from 'next/dist/shared/lib/app-router-context.shared-runtime'
import { useRouter } from 'next/navigation'
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import type { SignInResponse } from 'next-auth/react'

vi.mock('next/navigation', () => ({
  useRouter: vi.fn().mockReturnValue({ push: vi.fn(), refresh: vi.fn() }),
}))

vi.mock('next-auth/react', () => ({
  signIn: vi.fn(),
  useSession: vi.fn().mockReturnValue({ data: null }),
}))

import { signIn } from 'next-auth/react'
import { LoginForm } from '@/components/auth/LoginForm'

/** Build a router mock and register it with the useRouter() mock. */
function mockRouter(): { push: ReturnType<typeof vi.fn>; refresh: ReturnType<typeof vi.fn> } {
  const router = { push: vi.fn(), refresh: vi.fn() }
  vi.mocked(useRouter).mockReturnValue(router as unknown as AppRouterInstance)
  return router
}

/** Stub the credential pre-check response. */
function mockPreCheck(init: { ok: boolean; status?: number; detail?: string }) {
  const response = {
    ok: init.ok,
    status: init.status ?? (init.ok ? 200 : 401),
    json: async () => ({ detail: init.detail ?? '' }),
  }
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response))
}

function signInResult(value: { ok: boolean; error: string | null } | undefined) {
  vi.mocked(signIn).mockResolvedValue(value as unknown as SignInResponse)
}

async function fillCredentials(user: ReturnType<typeof userEvent.setup>, password = 'secret123') {
  await user.type(screen.getByLabelText('Email address'), 'user@example.com')
  await user.type(screen.getByLabelText('Password'), password)
  await user.click(screen.getByRole('button', { name: 'Sign in' }))
}

describe('LoginForm', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockRouter()
    mockPreCheck({ ok: true })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    sessionStorage.clear()
  })

  it('renders email and password fields and the submit button', () => {
    render(<LoginForm />)

    expect(screen.getByLabelText('Email address')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sign in' })).toBeInTheDocument()
  })

  it('shows validation error when email is empty on submit', async () => {
    const user = userEvent.setup()
    render(<LoginForm />)

    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => {
      expect(screen.getByText('Enter a valid email address')).toBeInTheDocument()
    })
  })

  it('shows validation error when email is malformed', async () => {
    const user = userEvent.setup()
    render(<LoginForm />)

    await user.type(screen.getByLabelText('Email address'), 'notanemail')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => {
      expect(screen.getByText('Enter a valid email address')).toBeInTheDocument()
    })
  })

  it('shows validation error when password is empty on submit', async () => {
    const user = userEvent.setup()
    render(<LoginForm />)

    await user.type(screen.getByLabelText('Email address'), 'user@example.com')
    await user.click(screen.getByRole('button', { name: 'Sign in' }))

    await waitFor(() => {
      expect(screen.getByText('Password is required')).toBeInTheDocument()
    })
  })

  it('calls signIn with credentials and the form values on valid submit', async () => {
    const user = userEvent.setup()
    signInResult({ ok: true, error: null })
    render(<LoginForm />)

    await fillCredentials(user)

    await waitFor(() => {
      expect(signIn).toHaveBeenCalledWith(
        'credentials',
        expect.objectContaining({
          email: 'user@example.com',
          password: 'secret123',
          redirect: false,
        }),
      )
    })
  })

  it('shows "Incorrect email or password." when the pre-check rejects the password', async () => {
    const user = userEvent.setup()
    mockPreCheck({ ok: false, status: 401, detail: 'Incorrect email or password' })
    render(<LoginForm />)

    await fillCredentials(user, 'wrongpass')

    await waitFor(() => {
      expect(screen.getByText('Incorrect email or password.')).toBeInTheDocument()
    })
    expect(signIn).not.toHaveBeenCalled()
  })

  it('shows the inline TOTP step when the pre-check reports TOTP is required', async () => {
    const user = userEvent.setup()
    mockPreCheck({ ok: false, status: 401, detail: 'TOTP code required' })
    render(<LoginForm />)

    await fillCredentials(user)

    await waitFor(() => {
      expect(screen.getByText('Two-factor authentication')).toBeInTheDocument()
    })
    expect(screen.getByLabelText('Authentication code')).toBeInTheDocument()
    // The session must not be established until the code is supplied.
    expect(signIn).not.toHaveBeenCalled()
  })

  it('never writes credentials to sessionStorage during the TOTP handoff', async () => {
    const user = userEvent.setup()
    mockPreCheck({ ok: false, status: 401, detail: 'TOTP code required' })
    render(<LoginForm />)

    await fillCredentials(user)

    await waitFor(() => {
      expect(screen.getByLabelText('Authentication code')).toBeInTheDocument()
    })
    expect(sessionStorage.length).toBe(0)
  })

  it('submits the TOTP code with the retained credentials', async () => {
    const user = userEvent.setup()
    mockPreCheck({ ok: false, status: 401, detail: 'TOTP code required' })
    signInResult({ ok: true, error: null })
    render(<LoginForm />)

    await fillCredentials(user)
    await waitFor(() => expect(screen.getByLabelText('Authentication code')).toBeInTheDocument())

    await user.type(screen.getByLabelText('Authentication code'), '123456')
    await user.click(screen.getByRole('button', { name: 'Verify Code' }))

    await waitFor(() => {
      expect(signIn).toHaveBeenCalledWith(
        'credentials',
        expect.objectContaining({
          email: 'user@example.com',
          password: 'secret123',
          totp_code: '123456',
          redirect: false,
        }),
      )
    })
  })

  it('redirects to /home on successful sign-in', async () => {
    const router = mockRouter()
    signInResult({ ok: true, error: null })

    const user = userEvent.setup()
    render(<LoginForm />)

    await fillCredentials(user)

    await waitFor(() => {
      expect(router.push).toHaveBeenCalledWith('/home')
    })
  })

  it('shows "Sign in failed." message when signIn returns null/undefined', async () => {
    signInResult(undefined)

    const user = userEvent.setup()
    render(<LoginForm />)

    await fillCredentials(user)

    await waitFor(() => {
      expect(screen.getByText('Sign in failed. Please try again.')).toBeInTheDocument()
    })
  })

  it('renders a button for the configured SSO provider', () => {
    render(<LoginForm providers={[{ provider: 'microsoft', label: 'Sign in with Microsoft' }]} />)

    expect(screen.getByRole('button', { name: 'Sign in with Microsoft' })).toBeInTheDocument()
  })

  it('renders no SSO buttons when no provider is configured', () => {
    render(<LoginForm />)

    expect(screen.queryByText('or continue with email')).not.toBeInTheDocument()
  })

  it('posts the credential form so an early submit cannot put the password in the URL', () => {
    render(<LoginForm />)

    // A form with no method defaults to GET, and a submit that beats hydration
    // is a real browser navigation: the password would land in the URL bar,
    // history, the referrer header and the server access log.
    const form = screen.getByRole('button', { name: 'Sign in' }).closest('form')
    expect(form).toHaveAttribute('method', 'post')
  })
})
