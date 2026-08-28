/**
 * Auth.js v5 middleware with role-based admin route protection.
 *
 * Uses the lightweight authConfig (no providers, no network calls) so the Edge
 * runtime never runs getEnabledProviders() on every request.
 *
 * Returning undefined from the auth() callback lets Auth.js handle the rest:
 * unauthenticated requests are redirected to /login automatically.
 */
import { NextResponse } from 'next/server'
import NextAuth from 'next-auth'
import { authConfig } from '@/lib/auth'

const { auth } = NextAuth(authConfig)

const ADMIN_PREFIXES = ['/admin']

const roleLevel: Record<string, number> = {
  superadmin: 4,
  admin: 3,
  analyst: 2,
  viewer: 1,
}

export default auth((req) => {
  const { pathname } = req.nextUrl
  const user = req.auth?.user as { role?: string; mfa_setup_required?: boolean } | undefined

  // MFA setup required: redirect to security settings (skip auth/api/static routes)
  if (
    user?.mfa_setup_required &&
    !pathname.startsWith('/settings/security') &&
    !pathname.startsWith('/api/') &&
    !pathname.startsWith('/login') &&
    !pathname.startsWith('/mfa')
  ) {
    return NextResponse.redirect(new URL('/settings/security', req.url))
  }

  // Authenticated admin-route check: redirect non-admins to home
  if (ADMIN_PREFIXES.some((prefix) => pathname.startsWith(prefix)) && user) {
    if ((roleLevel[user.role ?? 'viewer'] ?? 1) < 3) {
      return NextResponse.redirect(new URL('/home', req.url))
    }
  }
  // Returning undefined lets Auth.js redirect unauthenticated users to /login
})

// Every page reachable without an account is excluded here, not merely allowed
// through the callback: Auth.js redirects an unauthenticated request to /login
// before the callback runs, and an invitee following their link has no session
// to redirect back from.
//
// The pattern must be one string literal. Next.js reads this export by parsing
// the file, not by evaluating it, and fails the build on a concatenation with
// "Unsupported node type BinaryExpression".
export const config = {
  matcher: [
    '/((?!api|_next/static|_next/image|favicon.ico|login|register|accept-invite|forgot-password|reset-password).*)',
  ],
}
