'use client'

/**
 * Client half of the dashboards listing.
 *
 * The page itself is a Server Component (it fetches dashboards and freshness on
 * the server); search and the card/list toggle need client state, so the list
 * lives here. Card view keeps the bespoke DashboardCard, which polls per-card
 * data freshness.
 */
import { LayoutDashboard } from 'lucide-react'
import { DashboardCard } from '@/components/dashboards/DashboardCard'
import { Card, EmptyState } from '@/components/ui'
import { ResourceBrowser, type ResourceItem } from '@/components/portal/ResourceBrowser'

export interface DashboardSummary {
  id: number
  name: string
  description: string | null
  embed_type: 'powerbi' | 'tableau' | 'custom_react' | 'streamlit'
  is_public: boolean
  created_at: string
}

const EMBED_TYPE_LABELS: Record<DashboardSummary['embed_type'], string> = {
  powerbi: 'Power BI',
  tableau: 'Tableau',
  custom_react: 'Custom',
  streamlit: 'Streamlit',
}

export function DashboardList({ dashboards }: { dashboards: DashboardSummary[] }) {
  const items: ResourceItem[] = dashboards.map(d => ({
    key: d.id,
    href: `/dashboard/${d.id}`,
    icon: LayoutDashboard,
    title: d.name,
    description: d.description,
    badge: { label: EMBED_TYPE_LABELS[d.embed_type], tone: 'info' },
    meta: d.is_public ? ['Public'] : undefined,
    card: <DashboardCard dashboard={d} />,
  }))

  return (
    <ResourceBrowser
      items={items}
      storageKey="dashboards"
      searchPlaceholder="Search dashboards…"
      nameColumnLabel="Dashboard"
      gridClassName="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3"
      emptyState={
        <Card className="p-6">
          <EmptyState
            icon={LayoutDashboard}
            title="No dashboards yet"
            description="Dashboards you have access to appear here. An administrator can add one under Admin → Dashboards."
          />
        </Card>
      }
    />
  )
}
