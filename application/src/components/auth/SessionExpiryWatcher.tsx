'use client'

/**
 * Invisible component that detects session expiry and redirects to /login.
 *
 * Two expiry paths are handled:
 *   1. Refresh token exhausted — session.error === 'RefreshAccessTokenError',
 *      detected on the next Auth.js session refetch (up to 4 min polling interval
 *      or immediately on window focus).
 *   2. API 401 — the FastAPI access_token expired mid-session. lib/api.ts dispatches
 *      a global 'auth:expired' browser event; this component catches it and signs out.
 *
 * In both cases the user is redirected to /login?expired=1 so the login page can
 * show a "Your session has expired" message.
 */
import { useEffect, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { useSession, signOut } from 'next-auth/react'
import { toast } from 'sonner'

export function SessionExpiryWatcher() {
  const { data: session, status } = useSession()
  const wasAuthenticated = useRef(false)
  const signingOut = useRef(false)
  const router = useRouter()

  // Track whether the user has ever been authenticated in this tab
  useEffect(() => {
    if (status === 'authenticated') {
      wasAuthenticated.current = true
    }
  }, [status])

  // Path 1: session.error from a failed refresh token exchange
  useEffect(() => {
    if (session?.error === 'RefreshAccessTokenError' && !signingOut.current) {
      signingOut.current = true
      toast.error('Your session has expired. Please sign in again.')
      void signOut({ callbackUrl: '/login?expired=1' })
    }
  }, [session?.error])

  // Path 2: status flipped to unauthenticated after being authenticated
  useEffect(() => {
    if (status === 'unauthenticated' && wasAuthenticated.current && !signingOut.current) {
      signingOut.current = true
      router.replace('/login?expired=1')
    }
  }, [status, router])

  // Path 3: API 401 — dispatched by createClientFetch in lib/api.ts
  useEffect(() => {
    function handleExpired() {
      if (!signingOut.current) {
        signingOut.current = true
        toast.error('Your session has expired. Please sign in again.')
        void signOut({ callbackUrl: '/login?expired=1' })
      }
    }
    window.addEventListener('auth:expired', handleExpired)
    return () => window.removeEventListener('auth:expired', handleExpired)
  }, [])

  return null
}
