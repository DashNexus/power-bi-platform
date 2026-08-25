/**
 * Route guard for /dashboard and /dashboard/[id].
 *
 * Uses the same effective-features computation as the platform layout so that
 * a user sees the Dashboards link in the nav if and only if they can access
 * the page.
 */
import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { getAllFeatures } from '@/lib/features'
import { computeEffectiveFeatures } from '@/lib/portal'
import { AccessDenied } from '@/components/ui/AccessDenied'

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()
  if (!session?.user) redirect('/login')

  const rawFeatures = await getAllFeatures().catch(() => ({}) as Record<string, boolean>)
  const features = computeEffectiveFeatures(session.user.role ?? 'viewer', rawFeatures)

  if (!features['dashboards']) return <AccessDenied feature="Dashboards" />
  return <>{children}</>
}
