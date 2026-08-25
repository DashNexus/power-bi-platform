/**
 * Forgot password page.
 *
 * Accepts an email address and calls POST /auth/forgot-password. The API
 * always returns the same message whether or not the email is registered,
 * preventing user enumeration.
 */
'use client'

import { useState } from 'react'
import Link from 'next/link'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

// The page's metadata lives in ./layout.tsx — Next.js rejects a `metadata`
// export from a "use client" module, which broke the production build.

export default function ForgotPasswordPage() {
  const [email, setEmail] = useState('')
  const [submitted, setSubmitted] = useState(false)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!email.trim()) return
    setLoading(true)
    setError(null)
    try {
      await fetch(`${API_BASE}/auth/forgot-password`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ email: email.trim().toLowerCase() }),
      })
      setSubmitted(true)
    } catch {
      setError('Something went wrong. Please try again.')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="bg-card rounded-xl shadow-sm border border-border p-8">
      <div className="mb-6 text-center">
        <h1 className="text-2xl font-semibold text-foreground ">Forgot password?</h1>
        <p className="mt-1 text-sm text-muted-foreground ">
          We&apos;ll send a reset link to your email.
        </p>
      </div>

      {submitted ? (
        <div className="space-y-4 text-center">
          <div className="rounded-lg bg-success-subtle border border-success-subtle px-4 py-3 text-sm text-success-strong ">
            If that email address is registered, a password reset link has been sent.
            Check your inbox — the link expires in 1 hour.
          </div>
          <Link href="/login" className="text-sm text-primary hover:underline">
            Back to sign in
          </Link>
        </div>
      ) : (
        <form onSubmit={e => void handleSubmit(e)} className="space-y-4">
          <div>
            <label htmlFor="email" className="block text-sm font-medium text-foreground ">
              Email address
            </label>
            <input
              id="email"
              type="email"
              autoComplete="email"
              value={email}
              onChange={e => setEmail(e.target.value)}
              placeholder="name@company.com"
              className="mt-1 block w-full rounded-lg border border-border-strong bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground shadow-sm focus:outline-none focus:ring-2 focus:ring-ring"
              autoFocus
            />
          </div>

          {error && (
            <p className="rounded-lg bg-destructive-subtle border border-destructive-subtle px-3 py-2 text-sm text-destructive-strong ">
              {error}
            </p>
          )}

          <button
            type="submit"
            disabled={loading || !email.trim()}
            className="w-full rounded-lg bg-primary px-4 py-2.5 text-sm font-semibold text-primary-foreground hover:bg-primary-hover focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {loading ? 'Sending…' : 'Send Reset Link'}
          </button>

          <p className="text-center text-sm text-muted-foreground ">
            <Link href="/login" className="text-primary hover:underline">
              Back to sign in
            </Link>
          </p>
        </form>
      )}
    </div>
  )
}
