import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { getAllFeatures } from '@/lib/features'
import { getPortalSettings, getAccessibleResources, computeEffectiveFeatures } from '@/lib/portal'
import { AppShell } from '@/components/layout/AppShell'
import { SessionExpiryWatcher } from '@/components/auth/SessionExpiryWatcher'

export default async function PlatformLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()

  if (!session?.user) {
    redirect('/login')
  }

  const [rawFeatures, portalSettings] = await Promise.all([
    getAllFeatures().catch(() => ({}) as Record<string, boolean>),
    getPortalSettings(),
  ])

  const features = computeEffectiveFeatures(session.user.role ?? 'viewer', rawFeatures)

  // Only needed to filter deep links in an admin-authored nav, and each call is
  // a round-trip — so it is skipped entirely when the defaults are in use.
  const hasCustomNav = (portalSettings.nav_config?.length ?? 0) > 0
  const resourceAccess = hasCustomNav ? await getAccessibleResources() : null

  return (
    <>
      <SessionExpiryWatcher />
      <AppShell
        session={session}
        orgSettings={portalSettings}
        features={features}
        resourceAccess={resourceAccess}
      >
        {children}
      </AppShell>
    </>
  )
}
