'use client'

/**
 * Dashboard listing card.
 *
 * Shows name, description, embed type badge, data freshness, and a link to
 * the embed view. Polls the freshness endpoint every 60 seconds.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import { ExternalLink, RefreshCw } from 'lucide-react'
import { useSession } from 'next-auth/react'
import { cn } from '@/lib/utils'
import { createClientFetch } from '@/lib/api'

interface Dashboard {
  id: number
  name: string
  description: string | null
  embed_type: 'powerbi' | 'tableau' | 'custom_react' | 'streamlit'
  is_public: boolean
  created_at: string
}

interface DashboardCardProps {
  dashboard: Dashboard
}

interface FreshnessData {
  last_updated: string | null
}

const EMBED_TYPE_LABELS: Record<Dashboard['embed_type'], string> = {
  powerbi: 'Power BI',
  tableau: 'Tableau',
  custom_react: 'Custom',
  streamlit: 'Streamlit',
}

const EMBED_TYPE_COLORS: Record<Dashboard['embed_type'], string> = {
  powerbi: 'bg-warning-subtle text-warning-strong',
  tableau: 'bg-primary-subtle text-info-strong',
  custom_react: 'bg-purple-100 text-purple-800',
  streamlit: 'bg-success-subtle text-success-strong',
}

export function DashboardCard({ dashboard }: DashboardCardProps) {
  const { data: session } = useSession()
  const fetch = createClientFetch(session?.user?.access_token)
  const [freshness, setFreshness] = useState<FreshnessData | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [initialLoading, setInitialLoading] = useState(true)
  const prevIdRef = useRef(dashboard.id)

  const loadFreshness = useCallback(async () => {
    if (dashboard.id !== prevIdRef.current) {
      prevIdRef.current = dashboard.id
      setFreshness(null)
      setError(null)
      return
    }
    try {
      const data = await fetch<FreshnessData>(`/admin/dashboards/${dashboard.id}/freshness`)
      setFreshness(data)
      setError(null)
    } catch {
      setError('Freshness unavailable')
    } finally {
      setInitialLoading(false)
    }
  }, [dashboard.id, fetch])

  useEffect(() => {
    loadFreshness()
    const interval = setInterval(loadFreshness, 60_000)
    return () => clearInterval(interval)
  }, [loadFreshness])

  const freshnessLabel = freshness?.last_updated
    ? (() => {
        const diff = Date.now() - new Date(freshness.last_updated).getTime()
        const minutes = Math.floor(diff / 60_000)
        if (minutes < 1) return 'just now'
        if (minutes < 60) return `${minutes}m ago`
        const hours = Math.floor(minutes / 60)
        return `${hours}h ago`
      })()
    : null

  const freshnessColor = freshness?.last_updated
    ? (() => {
        const hoursSinceUpdate = freshness.last_updated
          ? (Date.now() - new Date(freshness.last_updated).getTime()) / 3_600_000
          : Infinity
        return hoursSinceUpdate > 24
          ? 'bg-warning-subtle text-warning-strong'
          : 'bg-success-subtle text-success-strong'
      })()
    : 'bg-muted text-muted-foreground'

  return (
    <div className="group flex flex-col rounded-xl border border-border bg-card p-5 shadow-sm hover:shadow-md transition-shadow duration-150">
      <div className="flex items-start justify-between gap-3 mb-3">
        <h2 className="text-sm font-semibold text-foreground leading-snug line-clamp-2">
          {dashboard.name}
        </h2>
        <div className="flex items-center gap-1.5 shrink-0">
          {!initialLoading && freshnessLabel && (
            <span
              className={cn(
                'inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
                freshnessColor,
              )}
            >
              <RefreshCw
                className={cn(
                  'h-2.5 w-2.5 mr-0.5',
                  freshnessColor.includes('amber') ? 'animate-spin-slow' : '',
                )}
              />
              {freshnessLabel}
            </span>
          )}
          {error && !freshnessLabel && (
            <span className="text-xs text-muted-foreground ">—</span>
          )}
          <span
            className={cn(
              'shrink-0 inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium',
              EMBED_TYPE_COLORS[dashboard.embed_type],
            )}
          >
            {EMBED_TYPE_LABELS[dashboard.embed_type]}
          </span>
        </div>
      </div>

      {dashboard.description && (
        <p className="text-xs text-muted-foreground line-clamp-3 mb-4 flex-1">
          {dashboard.description}
        </p>
      )}

      <div className="mt-auto pt-4 border-t border-border flex items-center justify-between">
        <span className="text-xs text-muted-foreground ">
          {dashboard.is_public ? 'Public' : 'Private'}
        </span>

        <Link
          href={`/dashboard/${dashboard.id}`}
          className={cn(
            'inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5',
            'text-xs font-medium text-primary-foreground hover:bg-primary-hover transition-colors duration-150',
            'focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2',
          )}
        >
          View Dashboard
          <ExternalLink className="h-3 w-3" />
        </Link>
      </div>
    </div>
  )
}
