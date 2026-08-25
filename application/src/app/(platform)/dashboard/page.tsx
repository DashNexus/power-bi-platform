import { formatDistanceToNow } from 'date-fns'
import { RefreshCw } from 'lucide-react'
import { apiFetch } from '@/lib/api'
import { Badge } from '@/components/ui/Badge'
import { PageHeader } from '@/components/ui/PageHeader'
import { DashboardList, type DashboardSummary as Dashboard } from './DashboardList'

export const metadata = {
  title: 'Dashboards',
}

interface FreshnessResponse {
  last_updated: string | null
}

async function getDashboards(): Promise<Dashboard[]> {
  try {
    return await apiFetch<Dashboard[]>('/dashboards')
  } catch {
    return []
  }
}

async function getDataFreshness(): Promise<FreshnessResponse> {
  try {
    return await apiFetch<FreshnessResponse>('/data/freshness')
  } catch {
    return { last_updated: null }
  }
}

export default async function DashboardsPage() {
  const [dashboards, freshness] = await Promise.all([getDashboards(), getDataFreshness()])

  const freshnessLabel = freshness.last_updated
    ? formatDistanceToNow(new Date(freshness.last_updated), { addSuffix: true })
    : null

  return (
    <div className="space-y-6">
      <PageHeader
        title="Dashboards"
        description={
          dashboards.length === 0
            ? undefined
            : `${dashboards.length} dashboard${dashboards.length === 1 ? '' : 's'}`
        }
        actions={
          freshnessLabel && (
            <Badge tone="success">
              <RefreshCw aria-hidden />
              Data refreshed {freshnessLabel}
            </Badge>
          )
        }
      />

      <DashboardList dashboards={dashboards} />
    </div>
  )
}
