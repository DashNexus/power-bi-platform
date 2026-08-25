/**
 * Route guard for /pipelines.
 *
 * Uses the same effective-features computation as the platform layout so a user
 * reaches the pipelines area only when the `pipelines` feature is enabled for
 * them (org flag AND a pipelines permission or a per-connection share).
 */
import { redirect } from 'next/navigation'
import { auth } from '@/lib/auth'
import { getAllFeatures } from '@/lib/features'
import { computeEffectiveFeatures } from '@/lib/portal'
import { AccessDenied } from '@/components/ui/AccessDenied'

export default async function PipelinesLayout({ children }: { children: React.ReactNode }) {
  const session = await auth()
  if (!session?.user) redirect('/login')

  const rawFeatures = await getAllFeatures().catch(() => ({}) as Record<string, boolean>)
  const features = computeEffectiveFeatures(session.user.role ?? 'viewer', rawFeatures)

  if (!features['pipelines']) return <AccessDenied feature="Data Pipelines" />
  return <>{children}</>
}
