/**
 * Auth.js v5 configuration.
 *
 * Credentials provider authenticates against the FastAPI backend POST /auth/token.
 * Microsoft Entra ID is the only SSO provider; it registers itself when the
 * `AZURE_AD_*` variables are present (see lib/authProviders.ts).
 */
import NextAuth from 'next-auth'
import type { NextAuthConfig } from 'next-auth'

// Derive Provider from NextAuth's own config to avoid @auth/core version conflicts.
type Provider = NonNullable<NextAuthConfig['providers']>[number]
import Credentials from 'next-auth/providers/credentials'
import MicrosoftEntraID from 'next-auth/providers/microsoft-entra-id'
import { getConfiguredProviders, type ConfiguredProvider } from '@/lib/authProviders'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

function buildOAuthProviders(configs: ConfiguredProvider[]): Provider[] {
  return configs.flatMap((config): Provider[] => {
    switch (config.provider) {
      case 'microsoft':
        return [
          MicrosoftEntraID({
            clientId: config.clientId,
            clientSecret: config.clientSecret,
            // A tenant ID scopes sign-in to one directory; without it Entra
            // falls back to the multi-tenant "common" issuer.
            ...(config.tenantId
              ? { issuer: `https://login.microsoftonline.com/${config.tenantId}/v2.0` }
              : {}),
          }) as Provider,
        ]
      default:
        return []
    }
  })
}

// Provider config is read synchronously from the environment (see
// lib/authProviders.ts for why the API cannot supply it). This previously did a
// top-level `await fetch()` of an admin-only endpoint, which always 401'd — so
// no OAuth provider was ever registered — while still blocking module
// evaluation on a network round-trip during build and every cold start.
const oauthProviders = buildOAuthProviders(getConfiguredProviders())

// Cookies are scoped by host, not by port, so every Auth.js app on localhost
// shares the default `authjs.session-token`. With the full platform running on
// the same machine, whichever app signed in last leaves a cookie the other
// cannot decrypt — surfacing as "JWTSessionError: no matching decryption
// secret" and a silent forced sign-out. A distinct name keeps the two apart.
//
// The `__Secure-` prefix is Auth.js's own convention and the browser refuses
// the cookie under it without `secure`, so the two must be decided together.
const useSecureCookies = process.env.NEXTAUTH_URL?.startsWith('https://') ?? false
const cookiePrefix = useSecureCookies ? '__Secure-' : ''

// Shared by the full config and by authConfig: the middleware reads the cookie
// through authConfig, so a name set on only one side means every request looks
// signed out.
export const authCookies = {
  sessionToken: {
    name: `${cookiePrefix}powerbi.session-token`,
    options: {
      httpOnly: true,
      sameSite: 'lax' as const,
      path: '/',
      secure: useSecureCookies,
    },
  },
}

export const { handlers, auth, signIn, signOut } = NextAuth({
  providers: [
    Credentials({
      name: 'Credentials',
      credentials: {
        email: { label: 'Email', type: 'email' },
        password: { label: 'Password', type: 'password' },
        totp_code: { label: 'TOTP Code', type: 'text' },
      },
      async authorize(credentials) {
        if (!credentials?.email || !credentials?.password) return null

        try {
          const res = await fetch(`${API_BASE}/auth/token`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              email: credentials.email,
              password: credentials.password,
              totp_code: credentials.totp_code ?? undefined,
            }),
          })

          if (!res.ok) return null

          const data = await res.json() as {
            access_token: string
            refresh_token: string
            expires_in: number
            user_id: number
            org_id: number
            role: string
            email: string
            name: string
            avatar_url?: string | null
            mfa_setup_required?: boolean
          }

          return {
            id: String(data.user_id),
            email: data.email,
            name: data.name,
            avatar_url: data.avatar_url ?? null,
            // Store extra fields — picked up in jwt callback
            user_id: data.user_id,
            org_id: data.org_id,
            role: data.role,
            access_token: data.access_token,
            refresh_token: data.refresh_token,
            expires_in: data.expires_in,
            mfa_setup_required: data.mfa_setup_required ?? false,
          }
        } catch {
          return null
        }
      },
    }),
    ...oauthProviders,
  ],

  session: { strategy: 'jwt' },
  cookies: authCookies,

  callbacks: {
    async jwt({ token, user, account, trigger, session: updatePayload }) {
      if (user) {
        // First sign-in — copy fields from the authorize() return value
        const u = user as typeof user & {
          user_id?: number
          org_id?: number
          role?: string
          access_token?: string
          refresh_token?: string
          expires_in?: number
          mfa_setup_required?: boolean
          avatar_url?: string | null
        }
        token.user_id = u.user_id
        token.org_id = u.org_id
        token.role = u.role
        token.access_token = u.access_token
        token.refresh_token = u.refresh_token
        token.access_token_expires_at = Date.now() + (u.expires_in ?? 3600) * 1000
        token.mfa_setup_required = u.mfa_setup_required ?? false
        token.avatar_url = u.avatar_url ?? null
      }

      // update() call from TotpEnrollment clears the mfa_setup_required flag
      if (trigger === 'update' && updatePayload && (updatePayload as Record<string, unknown>).totp_enabled === true) {
        token.mfa_setup_required = false
      }

      // update() from the profile page after an avatar upload or removal. The
      // key must be present rather than truthy: removing an avatar sends null.
      if (trigger === 'update' && updatePayload && 'avatar_url' in (updatePayload as object)) {
        token.avatar_url = (updatePayload as Record<string, unknown>).avatar_url as string | null
      }

      // Proactive token refresh — if within 5 minutes of expiry, call /auth/refresh
      const expiresAt = token.access_token_expires_at as number | undefined
      if (expiresAt && Date.now() > expiresAt - 5 * 60 * 1000) {
        try {
          const res = await fetch(`${API_BASE}/auth/refresh`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ refresh_token: token.refresh_token }),
          })
          if (res.ok) {
            const data = await res.json() as {
              access_token: string
              refresh_token: string
              expires_in: number
            }
            token.access_token = data.access_token
            token.refresh_token = data.refresh_token
            token.access_token_expires_at = Date.now() + data.expires_in * 1000
            delete token.error
          } else {
            token.error = 'RefreshAccessTokenError'
          }
        } catch {
          token.error = 'RefreshAccessTokenError'
        }
      }

      if (account?.access_token) {
        // OAuth sign-in — exchange the OAuth token for a platform JWT
        try {
          const res = await fetch(`${API_BASE}/auth/oauth-exchange`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
              provider: account.provider,
              access_token: account.access_token,
              id_token: account.id_token,
            }),
          })
          if (res.ok) {
            const data = await res.json() as {
              access_token: string
              user_id: number
              org_id: number
              role: string
            }
            token.access_token = data.access_token
            token.user_id = data.user_id
            token.org_id = data.org_id
            token.role = data.role
          }
        } catch {
          // OAuth exchange failed; token remains without platform fields
        }
      }

      return token
    },

    async session({ session, token }) {
      session.user = {
        ...session.user,
        user_id: token.user_id as number,
        org_id: token.org_id as number,
        role: token.role as string,
        email: token.email as string,
        access_token: token.access_token as string,
        totp_enabled: !!(token.mfa_setup_required === false && token.user_id),
        mfa_setup_required: (token.mfa_setup_required as boolean) ?? false,
        avatar_url: (token.avatar_url as string | null) ?? null,
      }
      if (token.error) {
        session.error = token.error as string
      }
      return session
    },
  },

  pages: {
    signIn: '/login',
    error: '/login',
  },
})

/**
 * Minimal auth config used by the middleware.
 *
 * Exported separately so middleware.ts can import it without pulling in the
 * full provider list (which makes a network call) on every edge invocation.
 *
 * The session callback here is required so that req.auth.user.role is
 * populated in middleware. Without it, Auth.js only puts the default JWT
 * claims (name, email, image) on session.user — custom fields stored by the
 * jwt callback are not forwarded automatically.
 */
export const authConfig = {
  pages: { signIn: '/login', error: '/login' },
  cookies: authCookies,
  callbacks: {
    authorized({ auth: session }: { auth: { user?: unknown } | null }) {
      return !!session?.user
    },
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    session(params: any) {
      // Forward custom token fields to session.user so middleware can read them.
      // This callback must be pure (no network calls) to stay Edge-runtime safe.
      const { session, token } = params as {
        session: { user?: Record<string, unknown> }
        token: Record<string, unknown>
      }
      if (session.user) {
        if (token.role !== undefined) session.user.role = token.role
        if (token.user_id !== undefined) session.user.user_id = token.user_id
        if (token.org_id !== undefined) session.user.org_id = token.org_id
        if (token.access_token !== undefined) session.user.access_token = token.access_token
        if (token.mfa_setup_required !== undefined) session.user.mfa_setup_required = token.mfa_setup_required
      }
      return session
    },
  },
  providers: [],
} as unknown as NextAuthConfig
