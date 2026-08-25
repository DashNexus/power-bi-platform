'use client'

/**
 * Sign-in form supporting credentials, TOTP, and OAuth providers.
 *
 * Two-step credential flow: the API is asked for a token first, purely to learn
 * whether the account requires TOTP, then the Auth.js session is established via
 * signIn(). The pre-check exists because Auth.js collapses every credential
 * failure to 'CredentialsSignin', making "wrong password" and "TOTP required"
 * indistinguishable afterwards.
 *
 * The TOTP step renders inline rather than on a separate /mfa route, so the
 * password lives only in this component's state for the duration of the flow.
 * The previous version handed it to the next page through sessionStorage, which
 * left the plaintext password readable for the rest of the tab session.
 */
import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { signIn } from 'next-auth/react'
import { useForm } from 'react-hook-form'
import { zodResolver } from '@hookform/resolvers/zod'
import { z } from 'zod'
import { ShieldCheck } from 'lucide-react'
import type { LoginProvider } from '@/lib/authProviders'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Input'
import { Alert } from '@/components/ui/Feedback'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

const loginSchema = z.object({
  email: z.string().email('Enter a valid email address'),
  password: z.string().min(1, 'Password is required'),
})

type LoginFormValues = z.infer<typeof loginSchema>

interface LoginFormProps {
  /** Enabled OAuth providers, resolved server-side by lib/authProviders.ts. */
  providers?: LoginProvider[]
}

export function LoginForm({ providers = [] }: LoginFormProps) {
  const router = useRouter()
  const [serverError, setServerError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  // Set once the API reports TOTP is required. Holds the already-verified
  // credentials in memory for the second step — never in any storage.
  const [pendingTotp, setPendingTotp] = useState<LoginFormValues | null>(null)
  const [totpCode, setTotpCode] = useState('')

  const {
    register,
    handleSubmit,
    formState: { errors },
  } = useForm<LoginFormValues>({ resolver: zodResolver(loginSchema) })

  /** Establish the Auth.js session, optionally with a TOTP code. */
  async function establishSession(values: LoginFormValues, code?: string): Promise<boolean> {
    const result = await signIn('credentials', {
      email: values.email,
      password: values.password,
      ...(code ? { totp_code: code } : {}),
      redirect: false,
    })
    if (!result || result.error) return false
    router.push('/home')
    router.refresh()
    return true
  }

  async function onSubmit(values: LoginFormValues) {
    setIsSubmitting(true)
    setServerError(null)

    try {
      const preCheck = await fetch(`${API_BASE}/auth/token`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: values.email, password: values.password }),
      })

      if (!preCheck.ok) {
        let detail = ''
        try {
          detail = ((await preCheck.json()) as { detail?: string }).detail ?? ''
        } catch {
          // A non-JSON error body tells us nothing extra; fall through.
        }

        if (preCheck.status === 401 && detail.includes('TOTP code required')) {
          // Password is correct — collect the code and finish in this component.
          setPendingTotp(values)
          setIsSubmitting(false)
          return
        }

        setServerError('Incorrect email or password.')
        setIsSubmitting(false)
        return
      }
    } catch {
      // Network failure on the pre-check — fall through to signIn, which will
      // also fail and surface the generic error below.
    }

    const ok = await establishSession(values)
    setIsSubmitting(false)
    if (!ok) setServerError('Sign in failed. Please try again.')
  }

  async function onTotpSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault()
    if (!pendingTotp) return

    if (totpCode.length !== 6) {
      setServerError('Enter the 6-digit code from your authenticator app.')
      return
    }

    setIsSubmitting(true)
    setServerError(null)
    const ok = await establishSession(pendingTotp, totpCode)
    setIsSubmitting(false)
    if (!ok) {
      setServerError('That code is incorrect or has expired. Try the next code.')
      setTotpCode('')
    }
  }

  if (pendingTotp) {
    return (
      <form onSubmit={onTotpSubmit} className="space-y-5">
        <div className="flex flex-col items-center gap-2 text-center">
          <ShieldCheck className="h-6 w-6 text-primary" aria-hidden />
          <p className="text-sm font-medium text-foreground">Two-factor authentication</p>
          <p className="text-sm text-muted-foreground">
            Enter the 6-digit code from your authenticator app for {pendingTotp.email}.
          </p>
        </div>

        <Field label="Authentication code" htmlFor="totp">
          <Input
            id="totp"
            autoFocus
            inputMode="numeric"
            autoComplete="one-time-code"
            placeholder="123456"
            maxLength={6}
            value={totpCode}
            onChange={e => {
              setTotpCode(e.target.value.replace(/\D/g, '').slice(0, 6))
              if (serverError) setServerError(null)
            }}
            className="text-center text-lg tracking-[0.4em]"
          />
        </Field>

        {serverError && <Alert tone="danger">{serverError}</Alert>}

        <Button type="submit" size="lg" isLoading={isSubmitting} className="w-full">
          Verify Code
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="w-full"
          onClick={() => {
            setPendingTotp(null)
            setTotpCode('')
            setServerError(null)
          }}
        >
          Use a different account
        </Button>
      </form>
    )
  }

  return (
    <div className="space-y-6">
      {providers.length > 0 && (
        <div className="space-y-3">
          {providers.map(p => (
            <Button
              key={p.provider}
              variant="outline"
              size="lg"
              className="w-full"
              onClick={() => signIn(p.provider, { callbackUrl: '/home' })}
            >
              {p.label}
            </Button>
          ))}

          <div className="relative">
            <div className="absolute inset-0 flex items-center" aria-hidden>
              <div className="w-full border-t border-border" />
            </div>
            <div className="relative flex justify-center text-sm">
              <span className="bg-card px-2 text-muted-foreground">or continue with email</span>
            </div>
          </div>
        </div>
      )}

      {/*
        method="post" only matters before hydration. A form with no method
        defaults to GET, so submitting early — a password manager autofilling
        and pressing Enter, a slow first compile — navigates to
        /login?email=…&password=… and writes the plaintext password into the
        URL bar, browser history, the referrer header and the server access
        log. handleSubmit() calls preventDefault, so once hydrated this
        attribute changes nothing; a pre-hydration submit now gets a 405
        instead of leaking the credentials.
      */}
      <form onSubmit={handleSubmit(onSubmit)} method="post" noValidate className="space-y-4">
        <Field label="Email address" htmlFor="email" error={errors.email?.message}>
          <Input
            id="email"
            type="email"
            autoComplete="email"
            placeholder="name@company.com"
            invalid={!!errors.email}
            {...register('email')}
          />
        </Field>

        <div className="space-y-1.5">
          <div className="flex items-center justify-between">
            <label htmlFor="password" className="block text-sm font-medium text-foreground">
              Password
            </label>
            <a href="/forgot-password" className="text-xs text-primary hover:underline">
              Forgot password?
            </a>
          </div>
          <Input
            id="password"
            type="password"
            autoComplete="current-password"
            invalid={!!errors.password}
            {...register('password')}
          />
          {errors.password && (
            <p role="alert" className="text-xs text-destructive-strong">
              {errors.password.message}
            </p>
          )}
        </div>

        {serverError && <Alert tone="danger">{serverError}</Alert>}

        <Button type="submit" size="lg" isLoading={isSubmitting} className="w-full">
          Sign in
        </Button>
      </form>
    </div>
  )
}
