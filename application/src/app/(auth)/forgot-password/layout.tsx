/**
 * Metadata carrier for the forgot-password route.
 *
 * The page itself is a Client Component, and Next.js forbids exporting
 * `metadata` from one, so the title is declared on this server layout instead.
 */
export const metadata = {
  title: 'Forgot password',
}

export default function ForgotPasswordLayout({ children }: { children: React.ReactNode }) {
  return children
}
