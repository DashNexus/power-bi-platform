'use client'

/**
 * Portal data pipelines listing page.
 *
 * Lists the pipeline connections shared with the current user (all, for admins),
 * each a favoritable card that opens the run monitor at /pipelines/{id}.
 */
import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { Workflow, Star, ExternalLink } from 'lucide-react'
import { createClientFetch } from '@/lib/api'

interface PipelineConnection {
  id: number
  name: string
  provider: string
  provider_label: string
  provider_implemented: boolean
}

interface Favorite {
  id: number
  resource_type: string
  resource_id: number
}

function PipelineCard({
  conn,
  isFavorite,
  onToggleFavorite,
}: {
  conn: PipelineConnection
  isFavorite: boolean
  onToggleFavorite: (id: number) => Promise<void>
}) {
  const [toggling, setToggling] = useState(false)

  async function handleFavorite(e: React.MouseEvent) {
    e.preventDefault()
    setToggling(true)
    try { await onToggleFavorite(conn.id) } finally { setToggling(false) }
  }

  return (
    <Link
      href={`/pipelines/${conn.id}`}
      className="group relative flex flex-col rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:shadow-md hover:border-border-strong "
    >
      <div className="flex items-start justify-between gap-3">
        <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border bg-sky-50 text-sky-600 border-sky-100 dark:bg-sky-900/30 dark:border-sky-700 dark:text-sky-400">
          <Workflow className="h-5 w-5" />
        </div>
        <button
          type="button"
          onClick={handleFavorite}
          disabled={toggling}
          aria-label={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
          className={`shrink-0 rounded-full p-1 transition-colors disabled:opacity-50 ${
 isFavorite ? 'text-amber-400 hover:text-amber-500' : 'text-muted-foreground hover:text-amber-400'
 }`}
        >
          <Star className={`h-4 w-4 ${isFavorite ? 'fill-current' : ''}`} />
        </button>
      </div>
      <div className="mt-3 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-foreground group-hover:text-primary transition-colors line-clamp-1">
            {conn.name}
          </h3>
          <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
      </div>
      <div className="mt-3">
        <span className="inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border bg-sky-50 text-sky-600 border-sky-100 dark:bg-sky-900/30 dark:border-sky-700 dark:text-sky-400">
          {conn.provider_label}
        </span>
        {!conn.provider_implemented && (
          <span className="ml-1.5 inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground">
            coming soon
          </span>
        )}
      </div>
    </Link>
  )
}

export default function PipelinesPage() {
  const { data: session } = useSession()
  const [connections, setConnections] = useState<PipelineConnection[]>([])
  const [favorites, setFavorites] = useState<Favorite[]>([])
  const [loading, setLoading] = useState(true)

  const token = session?.user?.access_token
  const apiFetch = useMemo(() => createClientFetch(token), [token])
  const favSet = new Set(
    favorites.filter(f => f.resource_type === 'data_pipeline').map(f => f.resource_id),
  )

  useEffect(() => {
    if (!session?.user?.access_token) return
    void (async () => {
      try {
        const [conns, favs] = await Promise.all([
          apiFetch<PipelineConnection[]>('/data-pipelines').catch(() => [] as PipelineConnection[]),
          apiFetch<Favorite[]>('/favorites').catch(() => [] as Favorite[]),
        ])
        setConnections(conns)
        setFavorites(favs)
      } finally {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  async function toggleFavorite(id: number) {
    if (favSet.has(id)) {
      try {
        await apiFetch(`/favorites/data_pipeline/${id}`, { method: 'DELETE' })
        setFavorites(prev => prev.filter(f => !(f.resource_type === 'data_pipeline' && f.resource_id === id)))
      } catch { toast.error('Failed to remove from favorites.') }
    } else {
      try {
        const fav = await apiFetch<Favorite>('/favorites', {
          method: 'POST',
          body: JSON.stringify({ resource_type: 'data_pipeline', resource_id: id }),
        })
        setFavorites(prev => [...prev, fav])
      } catch { toast.error('Failed to add to favorites.') }
    }
  }

  if (loading) {
    return <div className="flex h-64 items-center justify-center text-sm text-muted-foreground ">Loading…</div>
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-foreground ">Data Pipelines</h1>
        <p className="mt-1 text-sm text-muted-foreground ">
          {connections.length} pipeline connection{connections.length === 1 ? '' : 's'} available
        </p>
      </div>

      {connections.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-card py-16 text-center">
          <Workflow className="mb-3 h-10 w-10 text-muted-foreground " />
          <p className="text-sm font-medium text-foreground ">No pipeline connections available</p>
          <p className="mt-1 text-sm text-muted-foreground ">
            Ask your admin to share a data pipeline connection with your role.
          </p>
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {connections.map(conn => (
            <PipelineCard
              key={conn.id}
              conn={conn}
              isFavorite={favSet.has(conn.id)}
              onToggleFavorite={toggleFavorite}
            />
          ))}
        </div>
      )}
    </div>
  )
}
