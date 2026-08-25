import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { LoginForm } from '@/components/auth/LoginForm'
import { getLoginProviders } from '@/lib/authProviders'
import { Alert } from '@/components/ui/Feedback'
import { Brand } from '@/components/ui/Brand'

export const metadata = {
  title: 'Sign in',
}

export default async function LoginPage({
  searchParams,
}: {
  searchParams: Promise<{ expired?: string }>
}) {
  const session = await auth()

  if (session?.user) {
    redirect('/home')
  }

  const [{ expired }, providers] = await Promise.all([searchParams, getLoginProviders()])

  return (
    <div className="rounded-xl border border-border bg-card p-8 shadow-sm">
      <div className="mb-8 flex flex-col items-center text-center">
        <Brand size="lg" className="mb-4 flex-col gap-3" />
        <h1 className="text-2xl font-semibold tracking-tight text-foreground">Sign in</h1>
        <p className="mt-1 text-sm text-muted-foreground">Access your dashboards and reports</p>
      </div>
      {expired === '1' && (
        <Alert tone="warning" className="mb-4">
          Your session has expired. Sign in again to continue.
        </Alert>
      )}
      <LoginForm providers={providers} />
    </div>
  )
}
