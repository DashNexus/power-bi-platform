'use client'

/**
 * Portal data dictionary listing page.
 *
 * Lists the data dictionaries (one per warehouse) accessible to the current
 * user — those explicitly shared with their roles, or all when they hold
 * data_dictionary.manage. Searchable and switchable between card and list view;
 * each opens the individual dictionary browser at /data-dicts/{id}.
 */
import { useState, useEffect } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { NotebookText, BookOpen } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { Card, EmptyState, LoadingRows, PageHeader } from '@/components/ui'
import { ResourceBrowser, type ResourceItem } from '@/components/portal/ResourceBrowser'

interface DictWarehouse {
  id: number
  name: string
}

interface Favorite {
  id: number
  resource_type: string
  resource_id: number
}

export default function DataDictsPage() {
  const { data: session } = useSession()
  const [warehouses, setWarehouses] = useState<DictWarehouse[]>([])
  const [favorites, setFavorites] = useState<Favorite[]>([])
  const [loading, setLoading] = useState(true)

  const apiFetch = createClientFetch(session?.user?.access_token)
  const favSet = new Set(
    favorites.filter(f => f.resource_type === 'data_dictionary').map(f => f.resource_id),
  )

  useEffect(() => {
    if (!session?.user?.access_token) return
    void (async () => {
      try {
        const [dictData, favData] = await Promise.all([
          apiFetch<DictWarehouse[]>('/data-dictionary/warehouses').catch(
            () => [] as DictWarehouse[],
          ),
          apiFetch<Favorite[]>('/favorites').catch(() => [] as Favorite[]),
        ])
        setWarehouses(dictData)
        setFavorites(favData)
      } finally {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  async function toggleFavorite(id: number) {
    if (favSet.has(id)) {
      try {
        await apiFetch(`/favorites/data_dictionary/${id}`, { method: 'DELETE' })
        setFavorites(prev =>
          prev.filter(f => !(f.resource_type === 'data_dictionary' && f.resource_id === id)),
        )
      } catch {
        toast.error('Failed to remove from favorites.')
      }
    } else {
      try {
        const fav = await apiFetch<Favorite>('/favorites', {
          method: 'POST',
          body: JSON.stringify({ resource_type: 'data_dictionary', resource_id: id }),
        })
        setFavorites(prev => [...prev, fav])
      } catch {
        toast.error('Failed to add to favorites.')
      }
    }
  }

  const items: ResourceItem[] = warehouses.map(w => ({
    key: w.id,
    href: `/data-dicts/${w.id}`,
    icon: NotebookText,
    title: w.name,
    badge: { label: 'Data Dictionary', tone: 'danger' },
    favorite: { active: favSet.has(w.id), onToggle: () => toggleFavorite(w.id) },
  }))

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Dictionaries"
        description={`${warehouses.length} data dictionar${warehouses.length === 1 ? 'y' : 'ies'} available`}
      />

      {loading ? (
        <Card className="p-6">
          <LoadingRows rows={4} />
        </Card>
      ) : (
        <ResourceBrowser
          items={items}
          storageKey="data-dicts"
          searchPlaceholder="Search data dictionaries…"
          nameColumnLabel="Dictionary"
          emptyState={
            <Card className="p-6">
              <EmptyState
                icon={BookOpen}
                title="No data dictionaries available"
                description="A data dictionary documents what every table and column in a warehouse means. None have been shared with your role yet — ask an admin to grant access."
              />
            </Card>
          }
        />
      )}
    </div>
  )
}
