import { notFound } from 'next/navigation'
import { apiFetch } from '@/lib/api'
import { DashboardEmbedClient } from '@/components/dashboards/DashboardEmbedClient'
import type { EmbedType } from '@/types/embed'

interface DashboardConfig {
  id: number
  name: string
  description: string | null
  embed_type: EmbedType
  embed_url: string
  required_role: string
  dashboard_filters: Array<{
    filter_key: string
    filter_label: string
    filter_type: 'string' | 'date' | 'number' | 'select'
    default_value: string | null
    is_required: boolean
  }>
  settings: Record<string, unknown>
}

interface Filter {
  filter_key: string
  filter_label: string
  filter_type: 'string' | 'date' | 'number' | 'select'
  default_value: string | null
  is_required: boolean
}

async function getDashboard(id: string): Promise<DashboardConfig | null> {
  try {
    return await apiFetch<DashboardConfig>(`/dashboards/${id}`)
  } catch {
    return null
  }
}

export default async function DashboardDetailPage({
  params,
}: {
  params: Promise<{ id: string }>
}) {
  const { id } = await params
  const dashboard = await getDashboard(id)

  if (!dashboard) {
    notFound()
  }

  const filters: Filter[] = dashboard.dashboard_filters ?? []

  return (
    <div className="flex flex-col flex-1 min-h-0">
      {/* No background of its own — the embed shows the page through wherever the
          provider's document leaves it unpainted. */}
      {/* min-h floor: flex-1 alone lets a short viewport squeeze the embed to a
          few pixels. Scrolling the page instead is safe now that the scrollbar
          gutter is reserved. */}
      <div className="embed-surface min-h-[32rem] flex-1 overflow-hidden rounded-xl border border-border bg-transparent">
        <DashboardEmbedClient
          dashboard={{
            id: dashboard.id,
            embed_type: dashboard.embed_type,
            embed_url: dashboard.embed_url,
            filters,
          }}
        />
      </div>
    </div>
  )
}
