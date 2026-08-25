/**
 * Portal home page — /home.
 *
 * Renders the resource grid. The same grid is permanently available at
 * /resources, so a user always has a way back to it.
 */
export const dynamic = 'force-dynamic'

import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { getAllFeatures } from '@/lib/features'
import { computeEffectiveFeatures } from '@/lib/portal'
import PortalHomeClient from './PortalHomeClient'

export default async function PortalHomePage() {
  const session = await auth()
  if (!session?.user) redirect('/login')

  const rawFeatures = await getAllFeatures().catch(() => ({}) as Record<string, boolean>)
  const features = computeEffectiveFeatures(session.user.role ?? 'viewer', rawFeatures)

  return <PortalHomeClient features={features} />
}
