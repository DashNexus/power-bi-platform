'use client'

/**
 * Portal resource grid (client component).
 *
 * Aggregates all content a user can access — dashboards, pages, and Streamlit
 * apps — with per-item favorites toggling and filter controls. Receives the
 * effective feature set (feature flags + role visibility already applied by the
 * server) so quick-links, filter buttons, and API calls are gated without a
 * separate client-side fetch.
 */
import { useState, useEffect, useMemo } from 'react'
import Link from 'next/link'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import {
  LayoutDashboard,
  FileText,
  Star,
  ExternalLink,
  Zap,
  Download,
  NotebookText,
  Workflow,
  Search,
  LayoutGrid,
  List,
} from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '@/components/ui'
import { useViewMode } from '@/components/portal/useViewMode'
import { cn } from '@/lib/utils'

interface PortalHomeClientProps {
  features: Record<string, boolean>
  featuredHref?: string | null
  featuredLabel?: string | null
}

interface Dashboard {
  id: number
  name: string
  description: string | null
  slug: string
  embed_type: string
  tags: string[]
}

interface Page {
  id: number
  title: string
  slug: string
  tags: string[]
}

interface DataDictWarehouse {
  id: number
  name: string
}

interface PipelineConn {
  id: number
  name: string
  provider_label: string
}

interface Favorite {
  id: number
  resource_type: string
  resource_id: number
}

type FilterType = 'all' | 'dashboard' | 'page' | 'data_dictionary' | 'data_pipeline'
type ResourceType = 'dashboard' | 'page' | 'data_dictionary' | 'data_pipeline'

const TYPE_ICON: Record<ResourceType, typeof LayoutDashboard> = {
  dashboard: LayoutDashboard,
  page: FileText,
  data_dictionary: NotebookText,
  data_pipeline: Workflow,
}

const TYPE_COLOR: Record<string, string> = {
  dashboard: 'bg-primary-subtle text-primary border-primary/30',
  page: 'bg-assistant-subtle text-assistant border-purple-100',
  data_dictionary: 'bg-rose-50 text-rose-600 border-rose-100',
  data_pipeline: 'bg-sky-50 text-sky-600 border-sky-100',
}

const TYPE_LABEL: Record<string, string> = {
  dashboard: 'Dashboard',
  page: 'Page',
  data_dictionary: 'Data Dictionary',
  data_pipeline: 'Data Pipeline',
}

interface ResourceCardProps {
  id: number
  resourceType: ResourceType
  name: string
  description?: string | null
  href: string
  tags: string[]
  isFavorite: boolean
  onToggleFavorite: (type: string, id: number) => Promise<void>
}

function ResourceCard({
  id,
  resourceType,
  name,
  description,
  href,
  tags,
  isFavorite,
  onToggleFavorite,
}: ResourceCardProps) {
  const [toggling, setToggling] = useState(false)
  const Icon = TYPE_ICON[resourceType]

  async function handleFavorite(e: React.MouseEvent) {
    e.preventDefault()
    setToggling(true)
    try {
      await onToggleFavorite(resourceType, id)
    } finally {
      setToggling(false)
    }
  }

  return (
    <Link
      href={href}
      className="group relative flex flex-col rounded-xl border border-border bg-card p-5 shadow-sm transition-all hover:shadow-md hover:border-border-strong"
    >
      <div className="flex items-start justify-between gap-3">
        <div className={`flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border ${TYPE_COLOR[resourceType]}`}>
          <Icon className="h-5 w-5" />
        </div>
        <button
          type="button"
          onClick={handleFavorite}
          disabled={toggling}
          aria-label={isFavorite ? 'Remove from favorites' : 'Add to favorites'}
          className={`shrink-0 rounded-full p-1 transition-colors disabled:opacity-50 ${
 isFavorite
 ? 'text-amber-400 hover:text-amber-500'
 : 'text-muted-foreground hover:text-amber-400'
 }`}
        >
          <Star className={`h-4 w-4 ${isFavorite ? 'fill-current' : ''}`} />
        </button>
      </div>

      <div className="mt-3 flex-1">
        <div className="flex items-center gap-2">
          <h3 className="font-medium text-foreground group-hover:text-primary transition-colors line-clamp-1">
            {name}
          </h3>
          <ExternalLink className="h-3 w-3 shrink-0 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity" />
        </div>
        {description && (
          <p className="mt-1 text-sm text-muted-foreground line-clamp-2">{description}</p>
        )}
      </div>

      <div className="mt-3 flex flex-wrap items-center gap-1.5">
        <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium border ${TYPE_COLOR[resourceType]}`}>
          {TYPE_LABEL[resourceType]}
        </span>
        {tags.map(tag => (
          <span
            key={tag}
            className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
          >
            {tag}
          </span>
        ))}
      </div>
    </Link>
  )
}

export default function PortalHomeClient({ features, featuredHref, featuredLabel }: PortalHomeClientProps) {
  const { data: session } = useSession()
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [pages, setPages] = useState<Page[]>([])
  const [dataDicts, setDataDicts] = useState<DataDictWarehouse[]>([])
  const [pipelines, setPipelines] = useState<PipelineConn[]>([])
  const [favorites, setFavorites] = useState<Favorite[]>([])
  const [loading, setLoading] = useState(true)
  const [filter, setFilter] = useState<FilterType>('all')
  const [showFavoritesOnly, setShowFavoritesOnly] = useState(false)
  const [query, setQuery] = useState('')
  const [view, setView] = useViewMode('resources')

  const apiFetch = useMemo(
    () => createClientFetch(session?.user?.access_token),
    [session?.user?.access_token],
  )

  const hasDashboardsFeature = Boolean(features['dashboards'])
  const hasPagesFeature = Boolean(features['custom_pages'])
  const hasDataDictFeature = Boolean(features['governance'])
  const hasPipelinesFeature = Boolean(features['pipelines'])

  // Available filter types depend on which features are enabled.
  const availableFilters = useMemo<FilterType[]>(() => [
    'all',
    ...(hasDashboardsFeature ? (['dashboard'] as FilterType[]) : []),
    ...(hasPagesFeature ? (['page'] as FilterType[]) : []),
    ...(hasDataDictFeature ? (['data_dictionary'] as FilterType[]) : []),
    ...(hasPipelinesFeature ? (['data_pipeline'] as FilterType[]) : []),
  ], [hasDashboardsFeature, hasPagesFeature, hasDataDictFeature, hasPipelinesFeature])

  // Reset filter if it references a type that's no longer available
  useEffect(() => {
    if (!availableFilters.includes(filter)) setFilter('all')
  }, [availableFilters, filter])

  const favKey = (type: string, id: number) => `${type}:${id}`
  const favoriteSet = useMemo(
    () => new Set(favorites.map(f => favKey(f.resource_type, f.resource_id))),
    [favorites],
  )

  useEffect(() => {
    if (!session?.user?.access_token) return
    async function load() {
      try {
        const [dashData, pageData, dictData, pipelineData, favData] = await Promise.all([
          hasDashboardsFeature
            ? apiFetch<Dashboard[]>('/dashboards').catch(() => [] as Dashboard[])
            : Promise.resolve([] as Dashboard[]),
          hasPagesFeature
            ? apiFetch<Page[]>('/pages').catch(() => [] as Page[])
            : Promise.resolve([] as Page[]),
          hasDataDictFeature
            ? apiFetch<DataDictWarehouse[]>('/data-dictionary/warehouses').catch(() => [] as DataDictWarehouse[])
            : Promise.resolve([] as DataDictWarehouse[]),
          hasPipelinesFeature
            ? apiFetch<PipelineConn[]>('/data-pipelines').catch(() => [] as PipelineConn[])
            : Promise.resolve([] as PipelineConn[]),
          apiFetch<Favorite[]>('/favorites').catch(() => [] as Favorite[]),
        ])
        setDashboards(dashData)
        setPages(pageData)
        setDataDicts(dictData)
        setPipelines(pipelineData)
        setFavorites(favData)
      } finally {
        setLoading(false)
      }
    }
    void load()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  async function toggleFavorite(resourceType: string, resourceId: number) {
    const key = favKey(resourceType, resourceId)
    if (favoriteSet.has(key)) {
      try {
        await apiFetch(`/favorites/${resourceType}/${resourceId}`, { method: 'DELETE' })
        setFavorites(prev =>
          prev.filter(f => !(f.resource_type === resourceType && f.resource_id === resourceId)),
        )
      } catch {
        toast.error('Failed to remove from favorites.')
      }
    } else {
      try {
        const newFav = await apiFetch<Favorite>('/favorites', {
          method: 'POST',
          body: JSON.stringify({ resource_type: resourceType, resource_id: resourceId }),
        })
        setFavorites(prev => [...prev, newFav])
      } catch {
        toast.error('Failed to add to favorites.')
      }
    }
  }

  type ResourceItem = {
    key: string
    id: number
    type: ResourceType
    name: string
    description: string | null
    href: string
    tags: string[]
  }

  const allItems: ResourceItem[] = [
    ...dashboards.map(d => ({
      key: `dashboard:${d.id}`,
      id: d.id,
      type: 'dashboard' as const,
      name: d.name,
      description: d.description,
      href: `/dashboard/${d.id}`,
      tags: d.tags ?? [],
    })),
    ...pages.map(p => ({
      key: `page:${p.id}`,
      id: p.id,
      type: 'page' as const,
      name: p.title,
      description: null,
      href: `/pages/${p.slug}`,
      tags: p.tags ?? [],
    })),
    ...dataDicts.map(d => ({
      key: `data_dictionary:${d.id}`,
      id: d.id,
      type: 'data_dictionary' as const,
      name: d.name,
      description: null,
      href: `/data-dicts/${d.id}`,
      tags: [],
    })),
    ...pipelines.map(p => ({
      key: `data_pipeline:${p.id}`,
      id: p.id,
      type: 'data_pipeline' as const,
      name: p.name,
      description: p.provider_label,
      href: `/pipelines/${p.id}`,
      tags: [],
    })),
  ]

  const search = query.trim().toLowerCase()
  const visibleItems = allItems.filter(item => {
    if (filter !== 'all' && item.type !== filter) return false
    if (showFavoritesOnly && !favoriteSet.has(favKey(item.type, item.id))) return false
    if (
      search &&
      ![item.name, item.description, TYPE_LABEL[item.type], ...item.tags]
        .filter(Boolean)
        .join(' ')
        .toLowerCase()
        .includes(search)
    ) {
      return false
    }
    return true
  })

  const filterCounts: Record<string, number> = {
    dashboard: dashboards.length,
    page: pages.length,
    data_dictionary: dataDicts.length,
    data_pipeline: pipelines.length,
  }

  const userName = session?.user?.name ?? session?.user?.email ?? 'there'
  const firstName = userName.split(' ')[0]

  const quickLinks = [
    ...(features['exports'] ? [{
      href: '/exports',
      icon: Download,
      color: 'bg-teal-50 dark:bg-teal-900/30 text-teal-600 dark:text-teal-400',
      label: 'Exports',
      desc: 'Download data as CSV, Excel, or PDF',
    }] : []),
    ...(features['governance'] ? [{
      href: '/data-dicts',
      icon: NotebookText,
      color: 'bg-warning-subtle text-warning-strong ',
      label: 'Data Dictionary',
      desc: 'Explore table and column descriptions',
    }] : []),
    ...(features['pipelines'] ? [{
      href: '/pipelines',
      icon: Workflow,
      color: 'bg-sky-50 dark:bg-sky-900/30 text-sky-600 dark:text-sky-400',
      label: 'Data Pipelines',
      desc: 'Monitor pipeline runs and status',
    }] : []),
  ]

  const quickLinkCols =
    quickLinks.length <= 2 ? 'sm:grid-cols-2' :
    quickLinks.length === 3 ? 'sm:grid-cols-2 lg:grid-cols-3' :
    'sm:grid-cols-2 lg:grid-cols-4'

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Loading…
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold text-foreground">Welcome back, {firstName}</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {allItems.length} resource{allItems.length === 1 ? '' : 's'} available to you
        </p>
      </div>

      {/* Featured resource banner — shown when the org has configured a home resource */}
      {featuredHref && featuredLabel && (
        <div className="flex items-center justify-between rounded-xl border border-primary/40 bg-primary-subtle px-5 py-4">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wider text-primary mb-0.5">
              Featured
            </p>
            <p className="text-sm font-medium text-foreground ">{featuredLabel}</p>
          </div>
          <Link
            href={featuredHref}
            className="ml-4 shrink-0 inline-flex items-center gap-1.5 rounded-lg bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover transition-colors"
          >
            Open
            <ExternalLink className="h-3.5 w-3.5" />
          </Link>
        </div>
      )}

      {favorites.length > 0 && (
        <div>
          <h2 className="mb-3 flex items-center gap-2 text-sm font-semibold text-foreground">
            <Star className="h-4 w-4 fill-amber-400 text-amber-400" />
            Favorites
          </h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5">
            {allItems
              .filter(item => favoriteSet.has(favKey(item.type, item.id)))
              .map(item => (
                <ResourceCard
                  key={item.key}
                  id={item.id}
                  resourceType={item.type}
                  name={item.name}
                  description={item.description}
                  href={item.href}
                  tags={item.tags}
                  isFavorite
                  onToggleFavorite={toggleFavorite}
                />
              ))}
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-56 flex-1">
          <Search
            className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
            aria-hidden
          />
          <Input
            type="search"
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Search resources…"
            aria-label="Search resources"
            className="pl-9"
          />
        </div>
        <div
          className="flex items-center rounded-lg border border-border p-0.5"
          role="group"
          aria-label="View mode"
        >
          <Button
            variant={view === 'card' ? 'secondary' : 'ghost'}
            size="icon-sm"
            onClick={() => setView('card')}
            aria-pressed={view === 'card'}
            aria-label="Card view"
            title="Card view"
          >
            <LayoutGrid aria-hidden />
          </Button>
          <Button
            variant={view === 'list' ? 'secondary' : 'ghost'}
            size="icon-sm"
            onClick={() => setView('list')}
            aria-pressed={view === 'list'}
            aria-label="List view"
            title="List view"
          >
            <List aria-hidden />
          </Button>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        {availableFilters.map(f => (
          <button
            key={f}
            type="button"
            onClick={() => setFilter(f)}
            className={`rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
 filter === f
 ? 'bg-primary text-primary-foreground'
 : 'bg-card text-muted-foreground border border-border hover:bg-accent'
 }`}
          >
            {f === 'all' ? 'All' : TYPE_LABEL[f]}
            {f !== 'all' && (
              <span className="ml-1.5 text-xs opacity-75">
                {filterCounts[f] ?? 0}
              </span>
            )}
          </button>
        ))}
        <button
          type="button"
          onClick={() => setShowFavoritesOnly(v => !v)}
          className={`ml-auto flex items-center gap-1.5 rounded-full px-3 py-1.5 text-sm font-medium transition-colors ${
 showFavoritesOnly
 ? 'bg-warning-subtle text-warning-strong border border-warning-subtle'
 : 'bg-card text-muted-foreground border border-border hover:bg-accent'
 }`}
        >
          <Star className={`h-3.5 w-3.5 ${showFavoritesOnly ? 'fill-amber-500 text-amber-500' : ''}`} />
          Favorites only
        </button>
      </div>

      {visibleItems.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={search ? Search : Zap}
            title={
              search
                ? 'No matches'
                : showFavoritesOnly
                  ? 'No favourites in this category yet'
                  : 'Nothing available in this category'
            }
            description={
              search
                ? `Nothing here matches “${query.trim()}”. Try a shorter term, or switch the type filter to All.`
                : showFavoritesOnly
                  ? 'Click the star on any resource to add it to your favourites, and it will show up here.'
                  : 'Resources shared with your role appear here. Pick another type filter, or ask an admin to share something with you.'
            }
            action={
              search ? (
                <Button variant="outline" onClick={() => setQuery('')}>
                  Clear search
                </Button>
              ) : undefined
            }
          />
        </Card>
      ) : view === 'card' ? (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {visibleItems.map(item => (
            <ResourceCard
              key={item.key}
              id={item.id}
              resourceType={item.type}
              name={item.name}
              description={item.description}
              href={item.href}
              tags={item.tags}
              isFavorite={favoriteSet.has(favKey(item.type, item.id))}
              onToggleFavorite={toggleFavorite}
            />
          ))}
        </div>
      ) : (
        <Card className="overflow-hidden">
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell className="w-10">
                    <span className="sr-only">Favourite</span>
                  </TableHeaderCell>
                  <TableHeaderCell>Name</TableHeaderCell>
                  <TableHeaderCell>Description</TableHeaderCell>
                  <TableHeaderCell>Type</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {visibleItems.map(item => {
                  const Icon = TYPE_ICON[item.type]
                  const isFavorite = favoriteSet.has(favKey(item.type, item.id))
                  return (
                    <TableRow key={item.key} interactive>
                      <TableCell>
                        <button
                          type="button"
                          onClick={() => void toggleFavorite(item.type, item.id)}
                          aria-pressed={isFavorite}
                          aria-label={
                            isFavorite
                              ? `Remove ${item.name} from favourites`
                              : `Add ${item.name} to favourites`
                          }
                          className={cn(
                            'rounded-full p-1 transition-colors',
                            isFavorite
                              ? 'text-warning hover:text-warning-strong'
                              : 'text-muted-foreground hover:text-warning',
                          )}
                        >
                          <Star
                            className={cn('h-4 w-4', isFavorite && 'fill-current')}
                            aria-hidden
                          />
                        </button>
                      </TableCell>
                      <TableCell>
                        <Link
                          href={item.href}
                          className="flex items-center gap-2 font-medium text-foreground hover:text-primary"
                        >
                          <Icon className="h-4 w-4 shrink-0 text-muted-foreground" aria-hidden />
                          {item.name}
                        </Link>
                      </TableCell>
                      <TableCell muted className="max-w-md">
                        <span className="line-clamp-1">{item.description || '—'}</span>
                      </TableCell>
                      <TableCell>
                        <div className="flex flex-wrap items-center gap-1.5">
                          <Badge tone="info">{TYPE_LABEL[item.type]}</Badge>
                          {item.tags.map(tag => (
                            <Badge key={tag}>{tag}</Badge>
                          ))}
                        </div>
                      </TableCell>
                    </TableRow>
                  )
                })}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}

      {quickLinks.length > 0 && (
        <div className={`grid gap-3 border-t border-border pt-6 ${quickLinkCols}`}>
          {quickLinks.map(({ href, icon: Icon, color, label, desc }) => (
            <Link
              key={href}
              href={href}
              className="flex items-center gap-3 rounded-lg border border-border bg-card p-4 hover:shadow-sm transition-all hover:border-border-strong "
            >
              <div className={`flex h-9 w-9 items-center justify-center rounded-lg ${color}`}>
                <Icon className="h-4 w-4" />
              </div>
              <div>
                <p className="text-sm font-medium text-foreground ">{label}</p>
                <p className="text-xs text-muted-foreground ">{desc}</p>
              </div>
            </Link>
          ))}
        </div>
      )}
    </div>
  )
}
