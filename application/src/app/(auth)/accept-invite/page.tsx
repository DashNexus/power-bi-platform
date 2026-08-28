/**
 * Invitation accept page.
 *
 * Reads `?token=...`, asks the API what the invitation is for, and turns it
 * into an account. Reachable without a session — the token is the credential —
 * so `/accept-invite` is excluded from the middleware matcher.
 *
 * The state of the token is fetched before the form renders rather than
 * discovered on submit: an invitee holding a link that has expired or already
 * been used is told so, instead of filling in a password to be refused.
 *
 * The form is split out and wrapped in <Suspense> because useSearchParams()
 * opts a page out of static prerendering unless a boundary is present.
 */
'use client'

import { Suspense, useEffect, useState } from 'react'
import { useRouter, useSearchParams } from 'next/navigation'
import Link from 'next/link'
import { Button } from '@/components/ui/Button'
import { Field, Input } from '@/components/ui/Input'
import { Alert, Skeleton } from '@/components/ui/Feedback'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// Matches MIN_PASSWORD_LENGTH in api/app/services/invites.py; the API refuses
// anything shorter, so checking here only saves the round trip.
const MIN_PASSWORD_LENGTH = 12

interface InvitePreview {
  email: string
  org_name: string
  first_name: string | null
  last_name: string | null
  status: 'pending' | 'accepted' | 'expired'
  expires_at: string
}

const UNUSABLE: Record<'accepted' | 'expired', string> = {
  accepted: 'This invitation has already been used. Sign in with your email address and password.',
  expired: 'This invitation has expired. Ask an administrator to send you a new one.',
}

function AcceptInviteForm() {
  const router = useRouter()
  const token = useSearchParams().get('token') ?? ''

  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [loading, setLoading] = useState(true)
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  useEffect(() => {
    if (!token) {
      setError('This invitation link is missing its token. Ask for the link again.')
      setLoading(false)
      return
    }
    let cancelled = false
    fetch(`${API_BASE}/invites/${encodeURIComponent(token)}`)
      .then(async res => {
        if (!res.ok) throw new Error('invalid')
        return (await res.json()) as InvitePreview
      })
      .then(data => {
        if (cancelled) return
        setPreview(data)
        setFirstName(data.first_name ?? '')
        setLastName(data.last_name ?? '')
      })
      .catch(() => {
        if (!cancelled) setError('This invitation link is not valid. Ask for a new one.')
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })
    return () => {
      cancelled = true
    }
  }, [token])

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (password.length < MIN_PASSWORD_LENGTH) {
      setError(`Password must be at least ${MIN_PASSWORD_LENGTH} characters.`)
      return
    }
    if (password !== confirm) {
      setError('Passwords do not match.')
      return
    }

    setSaving(true)
    setError(null)
    try {
      const res = await fetch(`${API_BASE}/invites/${encodeURIComponent(token)}/accept`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          password,
          first_name: firstName || null,
          last_name: lastName || null,
        }),
      })
      const body = (await res.json()) as { detail?: string }
      if (!res.ok) {
        setError(body.detail ?? 'Could not set up your account. Ask for a new invitation.')
        return
      }
      setSuccess(true)
      setTimeout(() => router.push('/login'), 2500)
    } catch {
      setError('Could not reach the server. Check your connection and try again.')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <Skeleton className="h-72 w-full" />

  if (success) {
    return (
      <div className="space-y-4 text-center">
        <Alert tone="success">Your account is ready. Redirecting you to sign in…</Alert>
        <Link href="/login" className="text-sm text-primary hover:underline">
          Sign in now
        </Link>
      </div>
    )
  }

  if (!preview || preview.status !== 'pending') {
    return (
      <div className="space-y-4">
        <Alert tone="danger">
          {preview && preview.status !== 'pending' ? UNUSABLE[preview.status] : error}
        </Alert>
        <p className="text-center text-sm text-muted-foreground">
          <Link href="/login" className="text-primary hover:underline">
            Back to sign in
          </Link>
        </p>
      </div>
    )
  }

  return (
    <form onSubmit={e => void handleSubmit(e)} className="space-y-4">
      <Alert tone="info">
        You have been invited to <strong>{preview.org_name}</strong> as{' '}
        <strong>{preview.email}</strong>.
      </Alert>

      <div className="grid grid-cols-2 gap-3">
        <Field label="First name" htmlFor="first_name">
          <Input
            id="first_name"
            value={firstName}
            onChange={e => setFirstName(e.target.value)}
            autoComplete="given-name"
            autoFocus
          />
        </Field>
        <Field label="Last name" htmlFor="last_name">
          <Input
            id="last_name"
            value={lastName}
            onChange={e => setLastName(e.target.value)}
            autoComplete="family-name"
          />
        </Field>
      </div>

      <Field
        label="Password"
        htmlFor="password"
        hint={`At least ${MIN_PASSWORD_LENGTH} characters.`}
      >
        <Input
          id="password"
          type="password"
          autoComplete="new-password"
          value={password}
          onChange={e => setPassword(e.target.value)}
        />
      </Field>

      <Field label="Confirm password" htmlFor="confirm">
        <Input
          id="confirm"
          type="password"
          autoComplete="new-password"
          value={confirm}
          onChange={e => setConfirm(e.target.value)}
        />
      </Field>

      {error && <Alert tone="danger">{error}</Alert>}

      <Button type="submit" size="lg" isLoading={saving} className="w-full">
        Create Account
      </Button>
    </form>
  )
}

export default function AcceptInvitePage() {
  return (
    <div className="rounded-xl border border-border bg-card p-8 shadow-sm">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">
          Set up your account
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Choose a password to finish accepting your invitation.
        </p>
      </div>

      <Suspense fallback={<Skeleton className="h-72 w-full" />}>
        <AcceptInviteForm />
      </Suspense>
    </div>
  )
}
