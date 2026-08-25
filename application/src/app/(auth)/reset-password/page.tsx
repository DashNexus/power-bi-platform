/**
 * Password reset page.
 *
 * Reads `?token=...` from the URL, presents a new-password form, and calls
 * POST /auth/reset-password. On success redirects to /login.
 *
 * The form is split out and wrapped in <Suspense> because useSearchParams()
 * opts a page out of static prerendering unless a boundary is present — without
 * it, `next build` fails on this route.
 */
'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Input'
import { Alert, Skeleton } from '@/components/ui/Feedback'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

function ResetPasswordForm() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const token = searchParams.get('token') ?? ''

  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (!token) setError('This reset link is missing its token. Request a new link to continue.')
  }, [token])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (password.length < 8) {
      setError('Password must be at least 8 characters.')
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }

    setLoading(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/auth/reset-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ token, new_password: password }),
      })
      const body = (await res.json()) as { detail?: string; message?: string }
      if (!res.ok) {
        setError(body.detail ?? 'Password reset failed. Request a new link and try again.')
        return
      }
      setSuccess(true)
      setTimeout(() => router.push('/login'), 2500)
    } catch {
      setError('Password reset failed: could not reach the server. Check your connection and retry.')
    } finally {
      setLoading(false)
    }
  }

  if (success) {
    return (
      <div className="space-y-4 text-center">
        <Alert tone="success">Your password has been reset. Redirecting you to sign in…</Alert>
        <Link href="/login" className="text-sm text-primary hover:underline">
          Sign in now
        </Link>
      </div>
    )
  }

  return (
    <form onSubmit={e => void handleSubmit(e)} className="space-y-4">
      <Field label="New password" htmlFor="password" hint="At least 8 characters.">
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={e => setPassword(e.target.value)}
          disabled={!token}
          autoFocus
        />
      </Field>

      <Field label="Confirm password" htmlFor="confirm">
        <Input
          id="confirm"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={e => setConfirm(e.target.value)}
          disabled={!token}
        />
      </Field>

      {error && <Alert tone="danger">{error}</Alert>}

      <Button type="submit" size="lg" isLoading={loading} disabled={!token} className="w-full">
        Reset Password
      </Button>

      <p className="text-center text-sm text-muted-foreground">
        <Link href="/login" className="text-primary hover:underline">
          Back to sign in
        </Link>
      </p>
    </form>
  )
}

export default function ResetPasswordPage() {
  return (
    <div className="rounded-xl border border-border bg-card p-8 shadow-sm">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Set new password</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose a strong password at least 8 characters long.
        </p>
      </div>

      <Suspense fallback={<Skeleton className="h-56 w-full" />}>
        <ResetPasswordForm />
      </Suspense>
    </div>
  )
}
