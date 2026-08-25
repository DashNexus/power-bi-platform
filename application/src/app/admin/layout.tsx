import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { getAllFeatures } from '@/lib/features'
import { getPortalSettings, computeEffectiveFeatures } from '@/lib/portal'
import { hasRole } from '@/lib/permissions'
import { AppShell } from '@/components/layout/AppShell'

/**
 * Admin section layout.
 *
 * Requires at minimum the 'admin' role. Renders the same AppShell as the
 * platform layout so the sidebar and top bar appear on all admin pages, and
 * mirrors its data flow so admins see an identical nav on /admin/* pages.
 */
export default async function AdminLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()

  if (!session?.user) {
    redirect('/login')
  }

  if (!hasRole(session.user.role, 'admin')) {
    redirect('/home')
  }

  const [rawFeatures, portalSettings] = await Promise.all([
    getAllFeatures().catch(() => ({}) as Record<string, boolean>),
    getPortalSettings(),
  ])

  const features = computeEffectiveFeatures(session.user.role ?? 'viewer', rawFeatures)

  return (
    <AppShell session={session} orgSettings={portalSettings} features={features}>
      {children}
    </AppShell>
  )
}
