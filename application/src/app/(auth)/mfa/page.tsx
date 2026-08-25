import { redirect } from 'next/navigation'

/**
 * Legacy two-factor route.
 *
 * The TOTP challenge is now a second step inside LoginForm, so the password
 * never has to be handed between pages — it previously travelled through
 * sessionStorage in plaintext. Nothing links here any more; the route is kept so
 * bookmarks and the middleware's MFA-enrolment exemption land on the sign-in
 * flow rather than a 404.
 */
export default function MfaPage() {
  redirect('/login')
}
