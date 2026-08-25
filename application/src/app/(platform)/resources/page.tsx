/**
 * Resource grid — always available at /resources.
 *
 * Provides a stable URL for the default portal home (dashboards, apps, pages)
 * regardless of whether the org has configured /home to redirect elsewhere.
 * The avatar dropdown links here so users can always reach the full resource
 * list without needing to know the org's configured home destination.
 */
export const dynamic = 'force-dynamic'

import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { getAllFeatures } from '@/lib/features'
import { computeEffectiveFeatures } from '@/lib/portal'
import PortalHomeClient from '../home/PortalHomeClient'

export default async function ResourcesPage() {
  const session = await auth()
  if (!session?.user) redirect('/login')

  const rawFeatures = await getAllFeatures().catch(() => ({}) as Record<string, boolean>)

  const features = computeEffectiveFeatures(session.user.role ?? 'viewer', rawFeatures)

  return <PortalHomeClient features={features} />
}
