'use client'

/**
 * Client-side embed dispatcher for the dashboard detail page.
 *
 * Receives the dashboard config from the server component and dispatches on
 * embed_type: an authenticated Power BI report, or — for a `page` embed — an
 * ordinary URL in an iframe, which is also the fallback for anything unmapped.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import dynamic from 'next/dynamic'
import { useSession } from 'next-auth/react'
import { Maximize2, Minimize2 } from 'lucide-react'
import { Button } from '@/components/ui'
import type { EmbedType } from '@/types/embed'
import { FilterPanel } from './FilterPanel'
import { EmbedFrame } from './EmbedFrame'
import { normalizePublicEmbedUrl } from './publicEmbedUrl'
import { useThemeBackground } from './useThemeBackground'

// powerbi-client accesses `self`/`window` at module evaluation time. Static
// imports evaluate during SSR even inside 'use client' files, so this one is
// loaded only in the browser.
const PowerBIEmbed = dynamic(
  () => import('./PowerBIEmbed').then(m => ({ default: m.PowerBIEmbed })),
  { ssr: false },
)

interface DashboardEmbedProps {
  dashboard: {
    id: number
    embed_type: EmbedType
    embed_url: string
    filters: Array<{
      filter_key: string
      filter_label: string
      filter_type: 'string' | 'date' | 'number' | 'select'
      default_value: string | null
      is_required: boolean
    }>
  }
}

interface FilterValues {
  [key: string]: string
}

export function DashboardEmbedClient({ dashboard }: DashboardEmbedProps) {
  // Called for its side effect: redirects to /login when the session is gone.
  useSession({ required: true })
  const [filterValues, setFilterValues] = useState<FilterValues>({})
  const backgroundColor = useThemeBackground()
  const frameRef = useRef<HTMLDivElement>(null)
  const [isFullscreen, setIsFullscreen] = useState(false)

  const handleFilterChange = useCallback((key: string, value: string) => {
    setFilterValues(prev => ({ ...prev, [key]: value }))
  }, [])

  // Reset filters when dashboard id changes
  useEffect(() => {
    setFilterValues({})
  }, [dashboard.id])

  // Track fullscreen from the document, not from the click: Escape and the
  // browser's own controls exit it without going through the button.
  useEffect(() => {
    const sync = () => setIsFullscreen(document.fullscreenElement === frameRef.current)
    document.addEventListener('fullscreenchange', sync)
    return () => document.removeEventListener('fullscreenchange', sync)
  }, [])

  const toggleFullscreen = useCallback(() => {
    if (document.fullscreenElement) {
      void document.exitFullscreen()
    } else {
      // Rejects when the gesture is not user-activated; nothing to recover from.
      void frameRef.current?.requestFullscreen().catch(() => {})
    }
  }, [])

  const embedsByType: Partial<Record<EmbedType, React.ReactNode>> = {
    powerbi: <PowerBIEmbed dashboardId={dashboard.id} filters={filterValues} />,
  }

  return (
    <div className="flex h-full flex-col">
      {/* Filter panel — shown when filters are configured */}
      {dashboard.filters.length > 0 && (
        <div className="shrink-0 border-b border-border p-3">
          <FilterPanel
            filters={dashboard.filters}
            values={filterValues}
            onChange={handleFilterChange}
          />
        </div>
      )}

      {/* Embed area. The container is the fullscreen target, so a dashboard
          authored larger than the viewport can be given the whole screen rather
          than being panned inside a small frame. */}
      <div ref={frameRef} className="embed-surface group relative min-h-0 flex-1">
        <Button
          type="button"
          variant="secondary"
          size="icon-sm"
          onClick={toggleFullscreen}
          title={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          aria-label={isFullscreen ? 'Exit fullscreen' : 'Fullscreen'}
          // Fades in on hover so it never sits on top of the viz permanently,
          // but stays reachable by keyboard.
          className="absolute right-2 top-2 z-10 opacity-0 shadow-sm transition-opacity focus-visible:opacity-100 group-hover:opacity-100"
        >
          {isFullscreen ? <Minimize2 aria-hidden /> : <Maximize2 aria-hidden />}
        </Button>
        {embedsByType[dashboard.embed_type] ?? (
          // A pasted share link is rewritten here, not at save time, so dashboards
          // saved before this existed start embedding without being re-entered.
          <EmbedFrame
            src={normalizePublicEmbedUrl(dashboard.embed_url, { backgroundColor })}
            title=""
            className="h-full w-full"
          />
        )}
      </div>
    </div>
  )
}
