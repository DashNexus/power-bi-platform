'use client'

/**
 * Pipeline connection detail view.
 *
 * Three tabs: "Run History" (recent runs with time-window / name / status
 * filters and load-more pagination; ADF child runs nest under their parent),
 * "Pipelines" (the pipeline/flow definitions in the connection), and
 * "Notifications" (admin only). Reached from the portal listing (/pipelines) and
 * by clicking a connection on /admin/data-pipelines. A connection switcher lets
 * you swap connections in place.
 */
import { useState, useEffect, useCallback, useMemo } from 'react'
import { useParams, useRouter } from 'next/navigation'
import Link from 'next/link'
import { useSession } from 'next-auth/react'
import {
  ArrowLeft,
  Bell,
  ChevronDown,
  ChevronRight,
  Clock,
  ListTree,
  RefreshCw,
  Search,
  Workflow,
} from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { hasRole } from '@/lib/permissions'
import { PipelineNotificationsTab } from '@/components/pipelines/PipelineNotificationsTab'
import { Badge, StatusBadge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Alert, LoadingRows } from '@/components/ui/Feedback'
import { EmptyState } from '@/components/ui/EmptyState'
import { Input, Select } from '@/components/ui/Input'
import { DetailList, DetailRow, Modal } from '@/components/ui/Modal'
import { PageHeader } from '@/components/ui/PageHeader'
import {
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '@/components/ui/Table'
import { Tabs, type TabItem } from '@/components/ui/Tabs'
import { cn } from '@/lib/utils'

interface PipelineConnection {
  id: number
  name: string
  provider: string
  provider_label: string
  provider_implemented: boolean
}

interface PipelineRun {
  run_id: string | null
  name: string | null
  status: string | null
  started_at: string | null
  ended_at: string | null
  duration_ms: number | null
  message: string | null
  invoked_by_type?: string | null
  parent_run_id?: string | null
}

interface PipelineDef {
  name: string | null
  description: string | null
  activities_count: number | null
}

interface NotifStatus {
  enabled: boolean
  notify_on_success: boolean
  notify_on_failure: boolean
  overrides: Record<string, { notify_on_success?: boolean; notify_on_failure?: boolean }>
}

type Tab = 'runs' | 'pipelines' | 'notifications'

const DATE_RANGE_OPTIONS = [
  { value: 1, label: 'Last 24 hours' },
  { value: 7, label: 'Last 7 days' },
  { value: 14, label: 'Last 14 days' },
  { value: 30, label: 'Last 30 days' },
  { value: 90, label: 'Last 90 days' },
]

function formatDuration(ms: number | null): string {
  if (ms == null) return '—'
  const s = Math.round(ms / 1000)
  if (s < 60) return `${s}s`
  const m = Math.floor(s / 60)
  if (m < 60) return `${m}m ${s % 60}s`
  return `${Math.floor(m / 60)}h ${m % 60}m`
}

export default function PipelineDetailPage() {
  const { data: session } = useSession()
  const params = useParams<{ id: string }>()
  const router = useRouter()
  const pipelineId = Number(params.id)

  const [conn, setConn] = useState<PipelineConnection | null>(null)
  const [connections, setConnections] = useState<PipelineConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [tab, setTab] = useState<Tab>('runs')
  const isAdmin = hasRole(session?.user?.role, 'admin')

  // Run history state
  const [runs, setRuns] = useState<PipelineRun[]>([])
  const [nextCursor, setNextCursor] = useState<string | null>(null)
  const [refreshing, setRefreshing] = useState(false)
  const [loadingMore, setLoadingMore] = useState(false)
  const [runsError, setRunsError] = useState<string | null>(null)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [days, setDays] = useState(7)
  const [search, setSearch] = useState('')
  const [statusFilter, setStatusFilter] = useState('all')

  // Pipelines tab state
  const [pipelines, setPipelines] = useState<PipelineDef[]>([])
  const [pipelinesLoaded, setPipelinesLoaded] = useState(false)
  const [pipelinesLoading, setPipelinesLoading] = useState(false)
  const [pipelinesError, setPipelinesError] = useState<string | null>(null)

  // Notification status (badges) + detail modals
  const [notifStatus, setNotifStatus] = useState<NotifStatus | null>(null)
  const [selectedRun, setSelectedRun] = useState<PipelineRun | null>(null)
  const [selectedPipeline, setSelectedPipeline] = useState<PipelineDef | null>(null)

  const token = session?.user?.access_token
  const apiFetch = useMemo(() => createClientFetch(token), [token])

  function toggleExpand(id: string) {
    setExpanded(prev => {
      const next = new Set(prev)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return next
    })
  }

  const loadRuns = useCallback(
    async (opts?: { cursor?: string | null; append?: boolean }) => {
      setRunsError(null)
      const searchParams: Record<string, string | number> = { days }
      if (opts?.cursor) searchParams.cursor = opts.cursor
      try {
        const data = await apiFetch<{ runs: PipelineRun[]; next_cursor: string | null }>(
          `/data-pipelines/${pipelineId}/runs`,
          { searchParams },
        )
        setRuns(prev => (opts?.append ? [...prev, ...data.runs] : data.runs))
        setNextCursor(data.next_cursor ?? null)
      } catch (err) {
        if (!opts?.append) setRuns([])
        setRunsError(err instanceof Error ? err.message : 'Failed to load runs.')
      }
    },
    [apiFetch, pipelineId, days],
  )

  const loadPipelines = useCallback(async () => {
    setPipelinesLoading(true)
    setPipelinesError(null)
    try {
      const data = await apiFetch<{ pipelines: PipelineDef[] }>(
        `/data-pipelines/${pipelineId}/pipelines`,
      )
      setPipelines(data.pipelines ?? [])
    } catch (err) {
      setPipelines([])
      setPipelinesError(err instanceof Error ? err.message : 'Failed to load pipelines.')
    } finally {
      setPipelinesLoading(false)
      setPipelinesLoaded(true)
    }
  }, [apiFetch, pipelineId])

  // Load the connection + first page of runs (and the switcher list) on mount / id change.
  useEffect(() => {
    if (!session?.user?.access_token || Number.isNaN(pipelineId)) return
    setLoading(true)
    setPipelinesLoaded(false)
    setPipelines([])
    void (async () => {
      try {
        const c = await apiFetch<PipelineConnection>(`/data-pipelines/${pipelineId}`)
        setConn(c)
        apiFetch<PipelineConnection[]>('/data-pipelines').then(setConnections).catch(() => {})
        apiFetch<NotifStatus>(`/data-pipelines/${pipelineId}/notification-status`)
          .then(setNotifStatus)
          .catch(() => setNotifStatus(null))
        await loadRuns()
      } catch {
        setNotFound(true)
      } finally {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token, pipelineId])

  // Reload runs when the time window changes (but not on first mount, handled above).
  const [mounted, setMounted] = useState(false)
  useEffect(() => {
    if (!mounted) {
      setMounted(true)
      return
    }
    void loadRuns()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [days])

  // Lazy-load pipeline definitions the first time the Pipelines tab opens.
  useEffect(() => {
    if (tab === 'pipelines' && !pipelinesLoaded && !pipelinesLoading) void loadPipelines()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tab])

  async function handleRefresh() {
    setRefreshing(true)
    try {
      if (tab === 'runs') await loadRuns()
      else await loadPipelines()
    } finally {
      setRefreshing(false)
    }
  }

  async function handleLoadMore() {
    if (!nextCursor) return
    setLoadingMore(true)
    try {
      await loadRuns({ cursor: nextCursor, append: true })
    } finally {
      setLoadingMore(false)
    }
  }

  // Client-side filters over loaded runs.
  const statusOptions = useMemo(
    () => Array.from(new Set(runs.map(r => r.status).filter(Boolean))) as string[],
    [runs],
  )
  const filteredRuns = useMemo(() => {
    const q = search.trim().toLowerCase()
    return runs.filter(r => {
      if (statusFilter !== 'all' && r.status !== statusFilter) return false
      if (q && !(r.name ?? '').toLowerCase().includes(q)) return false
      return true
    })
  }, [runs, search, statusFilter])

  // Build a parent → children tree (ADF nests runs triggered by another pipeline).
  const visibleRows = useMemo(() => {
    const byId = new Map(filteredRuns.filter(r => r.run_id).map(r => [r.run_id as string, r]))
    const childrenByParent = new Map<string, PipelineRun[]>()
    for (const r of filteredRuns) {
      const p = r.parent_run_id
      if (p && byId.has(p)) {
        const arr = childrenByParent.get(p) ?? []
        arr.push(r)
        childrenByParent.set(p, arr)
      }
    }
    const roots = filteredRuns.filter(r => !(r.parent_run_id && byId.has(r.parent_run_id)))
    const rows: { run: PipelineRun; depth: number; childCount: number }[] = []
    const walk = (run: PipelineRun, depth: number): void => {
      const id = run.run_id ?? ''
      const kids = id ? (childrenByParent.get(id) ?? []) : []
      rows.push({ run, depth, childCount: kids.length })
      if (kids.length > 0 && expanded.has(id)) kids.forEach(k => walk(k, depth + 1))
    }
    roots.forEach(r => walk(r, 0))
    return rows
  }, [filteredRuns, expanded])

  if (loading) {
    return (
      <div className="space-y-6">
        <LoadingRows rows={6} />
      </div>
    )
  }

  if (notFound || !conn) {
    return (
      <div className="space-y-6">
        <Link
          href="/pipelines"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to Data Pipelines
        </Link>
        <EmptyState
          icon={Workflow}
          title="Pipeline connection not available"
          description="It may have been removed, or it is not shared with your role. Ask an administrator to grant you access."
        />
      </div>
    )
  }

  // Effective success/failure notification state for a pipeline (default + override).
  function effNotif(name: string | null): { success: boolean; failure: boolean } {
    if (!notifStatus || !notifStatus.enabled || !name) return { success: false, failure: false }
    const ov = notifStatus.overrides[name] ?? {}
    return {
      success: ov.notify_on_success ?? notifStatus.notify_on_success,
      failure: ov.notify_on_failure ?? notifStatus.notify_on_failure,
    }
  }

  const tabs: ReadonlyArray<TabItem<Tab>> = [
    { id: 'runs', label: 'Run History' },
    { id: 'pipelines', label: 'Pipelines' },
    ...(isAdmin
      ? [
          {
            id: 'notifications' as const,
            label: 'Notifications',
            badge: notifStatus?.enabled ? (
              <Badge tone="success">On</Badge>
            ) : (
              <Badge tone="neutral">Off</Badge>
            ),
          },
        ]
      : []),
  ]

  return (
    <div className="space-y-5">
      <div>
        <Link
          href="/pipelines"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground"
        >
          <ArrowLeft className="h-4 w-4" aria-hidden />
          Back to Data Pipelines
        </Link>
        <PageHeader
          className="mt-2"
          title={conn.name}
          description={conn.provider_label}
          actions={
            <>
              {connections.length > 1 && (
                <label className="flex items-center gap-1.5 text-xs text-muted-foreground">
                  <span className="hidden sm:inline">Connection</span>
                  <Select
                    value={pipelineId}
                    onChange={e => router.push(`/pipelines/${e.target.value}`)}
                    aria-label="Switch connection"
                    className="text-xs"
                  >
                    {connections.map(c => (
                      <option key={c.id} value={c.id}>
                        {c.name} · {c.provider_label}
                      </option>
                    ))}
                  </Select>
                </label>
              )}
              {tab !== 'notifications' && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => void handleRefresh()}
                  disabled={refreshing}
                >
                  <RefreshCw className={cn(refreshing && 'animate-spin')} aria-hidden />
                  Refresh
                </Button>
              )}
            </>
          }
        />
      </div>

      <Tabs tabs={tabs} active={tab} onChange={setTab} aria-label="Connection views" />

      {tab === 'notifications' && isAdmin && (
        <PipelineNotificationsTab
          connectionId={pipelineId}
          token={session?.user?.access_token ?? ''}
        />
      )}

      {tab === 'runs' && (
        <div className="space-y-4">
          <div className="flex flex-wrap items-center gap-2">
            <div className="relative w-56">
              <Search
                className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
                aria-hidden
              />
              <Input
                type="search"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Search pipeline name…"
                aria-label="Search runs by pipeline name"
                className="pl-8 text-xs"
              />
            </div>
            <Select
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
              aria-label="Filter by status"
              className="w-auto text-xs"
            >
              <option value="all">All statuses</option>
              {statusOptions.map(s => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </Select>
            <Select
              value={days}
              onChange={e => setDays(Number(e.target.value))}
              aria-label="Time window"
              className="w-auto text-xs"
            >
              {DATE_RANGE_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
            <span className="ml-auto text-xs text-muted-foreground">
              {filteredRuns.length} run{filteredRuns.length === 1 ? '' : 's'}
              {nextCursor && ' (more available)'}
            </span>
          </div>

          {runsError ? (
            <Alert tone="warning" title="Runs unavailable">
              {runsError}
            </Alert>
          ) : visibleRows.length === 0 ? (
            <EmptyState
              icon={Clock}
              title={
                search || statusFilter !== 'all' ? 'No runs match your filters' : 'No recent runs'
              }
              description={
                search || statusFilter !== 'all'
                  ? 'Clear the search or status filter, or widen the time window.'
                  : 'Nothing has run on this connection in the selected window. Try a longer time range.'
              }
            />
          ) : (
            <>
              <TableContainer>
                <Table>
                  <TableHead>
                    <TableRow>
                      <TableHeaderCell>Pipeline</TableHeaderCell>
                      <TableHeaderCell>Status</TableHeaderCell>
                      <TableHeaderCell>Started</TableHeaderCell>
                      <TableHeaderCell>Duration</TableHeaderCell>
                      <TableHeaderCell>Message</TableHeaderCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {visibleRows.map(({ run, depth, childCount }, i) => {
                      const id = run.run_id ?? ''
                      const isOpen = expanded.has(id)
                      return (
                        <TableRow
                          key={id || i}
                          interactive
                          onClick={() => setSelectedRun(run)}
                          className={cn(depth > 0 && 'bg-muted/40')}
                          title="View run details"
                        >
                          <TableCell className="font-medium">
                            <div
                              className="flex items-center gap-1.5"
                              style={{ paddingLeft: depth * 22 }}
                            >
                              {childCount > 0 ? (
                                <button
                                  type="button"
                                  onClick={e => {
                                    e.stopPropagation()
                                    if (id) toggleExpand(id)
                                  }}
                                  className="shrink-0 rounded p-0.5 text-muted-foreground hover:bg-secondary hover:text-foreground"
                                  aria-label={isOpen ? 'Collapse child runs' : 'Expand child runs'}
                                >
                                  {isOpen ? (
                                    <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                                  ) : (
                                    <ChevronRight className="h-3.5 w-3.5" aria-hidden />
                                  )}
                                </button>
                              ) : (
                                <span className="inline-flex w-[18px] shrink-0 justify-center text-muted-foreground">
                                  {depth > 0 ? '↳' : ''}
                                </span>
                              )}
                              <span className="truncate">{run.name ?? '—'}</span>
                              {childCount > 0 && (
                                <Badge
                                  tone="neutral"
                                  title={`${childCount} child ${childCount === 1 ? 'run' : 'runs'} triggered by this pipeline`}
                                >
                                  {childCount}
                                </Badge>
                              )}
                            </div>
                          </TableCell>
                          <TableCell>
                            <StatusBadge status={run.status} />
                          </TableCell>
                          <TableCell muted className="whitespace-nowrap">
                            {run.started_at ? new Date(run.started_at).toLocaleString() : '—'}
                          </TableCell>
                          <TableCell muted className="whitespace-nowrap">
                            {formatDuration(run.duration_ms)}
                          </TableCell>
                          <TableCell muted className="max-w-xs truncate" title={run.message ?? ''}>
                            {run.message ?? '—'}
                          </TableCell>
                        </TableRow>
                      )
                    })}
                  </TableBody>
                </Table>
              </TableContainer>
              {nextCursor && (
                <Button
                  variant="outline"
                  onClick={() => void handleLoadMore()}
                  isLoading={loadingMore}
                >
                  Load older runs
                </Button>
              )}
            </>
          )}
        </div>
      )}

      {tab === 'pipelines' && (
        <div className="space-y-4">
          {pipelinesLoading ? (
            <LoadingRows rows={4} />
          ) : pipelinesError ? (
            <Alert tone="warning" title="Pipelines unavailable">
              {pipelinesError}
            </Alert>
          ) : pipelines.length === 0 ? (
            <EmptyState
              icon={ListTree}
              title="No pipelines found"
              description="This connection did not report any pipeline definitions. Check that the connection's credentials can list pipelines."
            />
          ) : (
            <TableContainer>
              <Table>
                <TableHead>
                  <TableRow>
                    <TableHeaderCell>Pipeline</TableHeaderCell>
                    <TableHeaderCell>Description</TableHeaderCell>
                    <TableHeaderCell>Activities</TableHeaderCell>
                    <TableHeaderCell>Notifications</TableHeaderCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {pipelines.map((p, i) => {
                    const n = effNotif(p.name)
                    return (
                      <TableRow
                        key={p.name ?? i}
                        interactive
                        onClick={() => setSelectedPipeline(p)}
                        title="View pipeline details"
                      >
                        <TableCell className="font-medium">{p.name ?? '—'}</TableCell>
                        <TableCell muted className="max-w-md truncate" title={p.description ?? ''}>
                          {p.description ?? '—'}
                        </TableCell>
                        <TableCell muted>{p.activities_count ?? '—'}</TableCell>
                        <TableCell>
                          <div className="flex items-center gap-1.5">
                            <Badge tone={n.success ? 'success' : 'neutral'}>
                              Success {n.success ? 'on' : 'off'}
                            </Badge>
                            <Badge tone={n.failure ? 'danger' : 'neutral'}>
                              Failure {n.failure ? 'on' : 'off'}
                            </Badge>
                          </div>
                        </TableCell>
                      </TableRow>
                    )
                  })}
                </TableBody>
              </Table>
            </TableContainer>
          )}
          {!notifStatus?.enabled && isAdmin && pipelines.length > 0 && (
            <Alert tone="info">
              Run notifications are off for this connection, so every pipeline shows as off.{' '}
              <button
                type="button"
                onClick={() => setTab('notifications')}
                className="font-medium text-primary underline-offset-4 hover:underline"
              >
                <Bell className="mr-1 inline h-3.5 w-3.5" aria-hidden />
                Configure notifications
              </button>
            </Alert>
          )}
        </div>
      )}

      <Modal
        open={selectedRun !== null}
        onClose={() => setSelectedRun(null)}
        title={selectedRun?.name ?? 'Run'}
      >
        {selectedRun && (
          <DetailList>
            <DetailRow label="Status">
              <StatusBadge status={selectedRun.status} />
            </DetailRow>
            <DetailRow label="Run ID">
              <span className="font-mono text-xs">{selectedRun.run_id ?? '—'}</span>
            </DetailRow>
            <DetailRow label="Started">
              {selectedRun.started_at ? new Date(selectedRun.started_at).toLocaleString() : '—'}
            </DetailRow>
            <DetailRow label="Ended">
              {selectedRun.ended_at ? new Date(selectedRun.ended_at).toLocaleString() : '—'}
            </DetailRow>
            <DetailRow label="Duration">{formatDuration(selectedRun.duration_ms)}</DetailRow>
            {selectedRun.invoked_by_type && (
              <DetailRow label="Trigger">{selectedRun.invoked_by_type}</DetailRow>
            )}
            {selectedRun.parent_run_id && (
              <DetailRow label="Parent run">
                <span className="font-mono text-xs">{selectedRun.parent_run_id}</span>
              </DetailRow>
            )}
            <DetailRow label="Message">{selectedRun.message ?? '—'}</DetailRow>
          </DetailList>
        )}
      </Modal>

      <Modal
        open={selectedPipeline !== null}
        onClose={() => setSelectedPipeline(null)}
        title={selectedPipeline?.name ?? 'Pipeline'}
      >
        {selectedPipeline &&
          (() => {
            const n = effNotif(selectedPipeline.name)
            return (
              <DetailList>
                <DetailRow label="Description">{selectedPipeline.description ?? '—'}</DetailRow>
                <DetailRow label="Activities">{selectedPipeline.activities_count ?? '—'}</DetailRow>
                <DetailRow label="Success alerts">
                  <Badge tone={n.success ? 'success' : 'neutral'}>
                    {n.success ? 'Enabled' : 'Off'}
                  </Badge>
                </DetailRow>
                <DetailRow label="Failure alerts">
                  <Badge tone={n.failure ? 'danger' : 'neutral'}>
                    {n.failure ? 'Enabled' : 'Off'}
                  </Badge>
                </DetailRow>
              </DetailList>
            )
          })()}
      </Modal>
    </div>
  )
}
