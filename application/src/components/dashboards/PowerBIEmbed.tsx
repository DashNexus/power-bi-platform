'use client'

/**
 * Power BI report embed component.
 *
 * Fetches an embed token from the API on mount, then renders the report using
 * powerbi-client-react. Refreshes the token automatically 2 minutes before it
 * expires so the report stays live without a full page reload.
 */
import { useEffect, useRef, useState, useCallback } from 'react'
import { PowerBIEmbed as PBIEmbed } from 'powerbi-client-react'
import { models } from 'powerbi-client'
import { useSession } from 'next-auth/react'
import { createClientFetch, ApiError } from '@/lib/api'
import { cn } from '@/lib/utils'

interface EmbedTokenFilter {
  table: string
  column: string
  value: string
}

interface EmbedTokenResponse {
  token: string
  embed_url: string
  expiration: string
  embed_filters: EmbedTokenFilter[]
}

interface PowerBIEmbedProps {
  dashboardId: number
  filters: Record<string, string>
}

export function PowerBIEmbed({ dashboardId, filters }: PowerBIEmbedProps) {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [embedData, setEmbedData] = useState<EmbedTokenResponse | null>(null)
  const [isLoading, setIsLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [isConfigError, setIsConfigError] = useState(false)
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null)

  const fetchToken = useCallback(async () => {
    try {
      setError(null)
      const data = await apiFetch<EmbedTokenResponse>(
        `/embed/dashboards/${dashboardId}/embed-token`,
        { method: 'POST' },
      )
      setEmbedData(data)

      // Schedule a refresh 2 minutes before the token expires
      const expiresAt = new Date(data.expiration).getTime()
      const refreshIn = expiresAt - Date.now() - 2 * 60 * 1000
      if (refreshIn > 0) {
        refreshTimerRef.current = setTimeout(() => {
          fetchToken()
        }, refreshIn)
      }
    } catch (exc) {
      if (exc instanceof ApiError) {
        // 400 from the embed endpoint means a Power BI configuration problem —
        // retrying won't help, so flag it separately to suppress the retry button.
        setIsConfigError(exc.status === 400)
        setError(exc.message)
      } else {
        setIsConfigError(false)
        setError('Failed to load the dashboard.')
      }
    } finally {
      setIsLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, session?.user?.access_token])

  useEffect(() => {
    if (!session) return
    fetchToken()
    return () => {
      if (refreshTimerRef.current) clearTimeout(refreshTimerRef.current)
    }
  }, [fetchToken, session])

  // Admin-configured RLS filters (resolved server-side against the current user's attributes)
  const adminFilters = (embedData?.embed_filters ?? [])
    .filter(f => f.value !== '')
    .map(f => ({
      $schema: 'http://powerbi.com/product/schema#basic',
      target: { table: f.table, column: f.column },
      operator: 'In',
      values: [f.value],
      filterType: models.FilterType.Basic,
    }))

  // User-facing runtime filters from FilterPanel
  const userFilters = Object.entries(filters)
    .filter(([, v]) => v !== '')
    .map(([key, value]) => ({
      $schema: 'http://powerbi.com/product/schema#basic',
      target: { table: 'Data', column: key },
      operator: 'In',
      values: [value],
      filterType: models.FilterType.Basic,
    }))

  const pbiFilters = [...adminFilters, ...userFilters]

  if (isLoading) {
    return (
      <div className="flex h-full w-full items-center justify-center">
        <div className="space-y-3 w-full px-6">
          <div className="h-4 w-2/3 animate-pulse rounded bg-secondary" />
          <div className="h-64 w-full animate-pulse rounded-lg bg-secondary" />
          <div className="h-4 w-1/2 animate-pulse rounded bg-secondary" />
        </div>
      </div>
    )
  }

  if (error || !embedData) {
    return (
      <div className="flex h-full w-full flex-col items-center justify-center gap-4 p-8">
        {isConfigError ? (
          <div className="w-full max-w-lg rounded-lg border border-warning-subtle bg-warning-subtle p-5 text-sm">
            <p className="font-semibold text-amber-900 mb-2">Power BI configuration error</p>
            <p className="text-warning-strong leading-relaxed">{error}</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
            <p>{error ?? 'Dashboard could not be loaded.'}</p>
            <button
              type="button"
              onClick={() => {
                setIsLoading(true)
                fetchToken()
              }}
              className={cn(
                'rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground',
                'hover:bg-primary-hover transition-colors',
              )}
            >
              Retry
            </button>
          </div>
        )}
      </div>
    )
  }

  return (
    <PBIEmbed
      embedConfig={{
        type: 'report',
        embedUrl: embedData.embed_url,
        accessToken: embedData.token,
        tokenType: models.TokenType.Embed,
        filters: pbiFilters,
        settings: {
          panes: {
            filters: { visible: false },
            pageNavigation: { visible: true },
          },
          background: models.BackgroundType.Transparent,
        },
      }}
      cssClassName="w-full h-full"
    />
  )
}
