/**
 * Admin landing page.
 *
 * /admin had no index — it 404'd, so every admin arrived through a sidebar link
 * with no sense of the organisation's overall state. One server-side request
 * backs the whole page, so it renders without a loading flash; the admin layout
 * already handles the role redirect.
 */
import { apiFetch } from '@/lib/api'
import { ErrorState } from '@/components/ui'
import { AdminOverview, type AdminOverviewData } from '@/components/admin/AdminOverview'

export const metadata = {
  title: 'Admin overview',
}

async function getOverview(): Promise<AdminOverviewData | null> {
  try {
    return await apiFetch<AdminOverviewData>('/admin/overview')
  } catch {
    return null
  }
}

export default async function AdminOverviewPage() {
  const data = await getOverview()

  if (!data) {
    return (
      <div className="max-w-6xl">
        <ErrorState description="The overview could not be loaded. The API may be unreachable — reload to try again." />
      </div>
    )
  }

  return <AdminOverview data={data} />
}
