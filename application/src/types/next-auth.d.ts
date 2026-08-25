import type { DefaultSession } from 'next-auth'

declare module 'next-auth' {
  interface Session {
    user: {
      user_id: number
      org_id: number
      role: string
      email: string
      access_token: string
      totp_enabled: boolean
      mfa_setup_required: boolean
      /**
       * App-relative avatar path, refreshed via `useSession().update()` after
       * an upload — the JWT would otherwise show the old image until re-login.
       */
      avatar_url?: string | null
    } & DefaultSession['user']
    /** Set to 'RefreshAccessTokenError' when the refresh token has expired. */
    error?: string
  }
}
