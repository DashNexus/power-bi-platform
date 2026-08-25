'use client'

/**
 * Table of SQL reports, scheduled and on-demand alike.
 *
 * Each row can be run, edited, deleted, and expanded to show its run history.
 * Running is asynchronous — the API queues a job and the worker picks it up —
 * so a row that has just been started polls until the run reaches a terminal
 * state rather than claiming success it cannot know about.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import {
  ChevronDown,
  ChevronRight,
  Clock,
  Database,
  Download,
  Mail,
  Pencil,
  Play,
  Server,
  Trash2,
} from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { RunHistory } from '@/components/exports/RunHistory'
import type { ExportRun, Report } from '@/components/exports/types'
import {
  Alert,
  Badge,
  Button,
  EmptyState,
  LoadingRows,
  StatusBadge,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '@/components/ui'

interface ReportsTableProps {
  /** Bumped by the page when a report is created, to force a reload. */
  refreshToken?: number
  onEdit: (report: Report) => void
}

const DELIVERY_ICONS: Record<string, React.ReactNode> = {
  email: <Mail className="h-3.5 w-3.5" aria-hidden />,
  sftp: <Server className="h-3.5 w-3.5" aria-hidden />,
  download: <Download className="h-3.5 w-3.5" aria-hidden />,
}

const TERMINAL = new Set(['completed', 'failed'])
const POLL_MS = 4000

export function ReportsTable({ refreshToken = 0, onEdit }: ReportsTableProps) {
  const { data: session } = useSession()
  const token = session?.user?.access_token

  const [reports, setReports] = useState<Report[]>([])
  const [latest, setLatest] = useState<Record<number, ExportRun | undefined>>({})
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<number | null>(null)
  const [expanded, setExpanded] = useState<number | null>(null)
  const pollRef = useRef<ReturnType<typeof setInterval> | null>(null)

  const loadReports = useCallback(async () => {
    if (!token) return
    try {
      const apiFetch = createClientFetch(token)
      const data = await apiFetch<Report[]>('/exports/reports')
      setReports(data)
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load reports.')
    } finally {
      setLoading(false)
    }
  }, [token])

  /** Refresh the most recent run of every report, for the status column. */
  const loadLatestRuns = useCallback(async () => {
    if (!token) return
    const apiFetch = createClientFetch(token)
    try {
      // One call for all reports rather than one per row: the run log is
      // already ordered newest-first, so the first hit per schedule wins.
      const runs = await apiFetch<ExportRun[]>('/exports/jobs?limit=200')
      const byReport: Record<number, ExportRun> = {}
      for (const run of runs) {
        if (run.schedule_id !== null && byReport[run.schedule_id] === undefined) {
          byReport[run.schedule_id] = run
        }
      }
      setLatest(byReport)
    } catch {
      // The status column degrades to "—"; the table itself still works.
    }
  }, [token])

  useEffect(() => {
    loadReports()
    loadLatestRuns()
  }, [loadReports, loadLatestRuns, refreshToken])

  // Poll only while something is in flight, and stop as soon as it is not.
  const hasActiveRun = Object.values(latest).some(
    run => run !== undefined && !TERMINAL.has(run.status),
  )
  useEffect(() => {
    if (!hasActiveRun) {
      if (pollRef.current) {
        clearInterval(pollRef.current)
        pollRef.current = null
      }
      return
    }
    pollRef.current = setInterval(() => {
      loadLatestRuns()
      loadReports()
    }, POLL_MS)
    return () => {
      if (pollRef.current) clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [hasActiveRun, loadLatestRuns, loadReports])

  async function handleRun(reportId: number) {
    if (!token) return
    setBusyId(reportId)
    setError(null)
    try {
      const apiFetch = createClientFetch(token)
      const run = await apiFetch<ExportRun>(`/exports/reports/${reportId}/run`, { method: 'POST' })
      setLatest(prev => ({ ...prev, [reportId]: run }))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not start the report.')
    } finally {
      setBusyId(null)
    }
  }

  async function handleDelete(report: Report) {
    if (!token) return
    if (!confirm(`Delete "${report.name}"? Its run history is kept.`)) return
    try {
      const apiFetch = createClientFetch(token)
      await apiFetch<unknown>(`/exports/reports/${report.id}`, { method: 'DELETE' })
      setReports(prev => prev.filter(r => r.id !== report.id))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not delete the report.')
    }
  }

  if (loading) return <LoadingRows />

  if (reports.length === 0) {
    return (
      <EmptyState
        icon={Database}
        title="No reports yet"
        description="A report runs a read-only query against a warehouse connection or the operations database, on a schedule or on demand."
      />
    )
  }

  return (
    <div className="space-y-3">
      {error && <Alert tone="danger">{error}</Alert>}

      <TableContainer>
        <Table>
          <TableHead>
            <TableRow>
              <TableHeaderCell className="w-8" />
              <TableHeaderCell>Name</TableHeaderCell>
              <TableHeaderCell>Source</TableHeaderCell>
              <TableHeaderCell>Runs</TableHeaderCell>
              <TableHeaderCell>Format</TableHeaderCell>
              <TableHeaderCell>Delivery</TableHeaderCell>
              <TableHeaderCell>Last run</TableHeaderCell>
              <TableHeaderCell className="text-right">Actions</TableHeaderCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {reports.map(report => {
              const run = latest[report.id]
              const isOpen = expanded === report.id
              const inFlight = run !== undefined && !TERMINAL.has(run.status)
              return [
                <TableRow key={report.id}>
                  <TableCell>
                    <button
                      type="button"
                      onClick={() => setExpanded(isOpen ? null : report.id)}
                      aria-label={isOpen ? 'Hide run history' : 'Show run history'}
                      aria-expanded={isOpen}
                      className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground"
                    >
                      {isOpen ? (
                        <ChevronDown className="h-4 w-4" aria-hidden />
                      ) : (
                        <ChevronRight className="h-4 w-4" aria-hidden />
                      )}
                    </button>
                  </TableCell>
                  <TableCell className="font-medium text-foreground">{report.name}</TableCell>
                  <TableCell>
                    <Badge tone={report.source_kind === 'operations' ? 'warning' : 'neutral'}>
                      {report.source_kind === 'operations' ? 'Operations DB' : 'Warehouse'}
                    </Badge>
                  </TableCell>
                  <TableCell>
                    {report.cron_expression ? (
                      <span className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
                        <Clock className="h-3.5 w-3.5" aria-hidden />
                        <code className="font-mono">{report.cron_expression}</code>
                        {!report.is_active && <Badge tone="neutral">Paused</Badge>}
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">On demand</span>
                    )}
                  </TableCell>
                  <TableCell className="text-xs uppercase text-muted-foreground">
                    {report.format}
                  </TableCell>
                  <TableCell>
                    <span className="inline-flex items-center gap-1.5 text-xs capitalize text-muted-foreground">
                      {DELIVERY_ICONS[report.delivery_method] ?? null}
                      {report.delivery_method}
                    </span>
                  </TableCell>
                  <TableCell>
                    {run ? (
                      <span className="inline-flex items-center gap-2">
                        <StatusBadge status={run.status} />
                        <span className="text-xs text-muted-foreground">
                          {new Date(run.created_at).toLocaleString()}
                        </span>
                      </span>
                    ) : (
                      <span className="text-xs text-muted-foreground">Never</span>
                    )}
                  </TableCell>
                  <TableCell className="text-right">
                    <div className="flex items-center justify-end gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleRun(report.id)}
                        isLoading={busyId === report.id}
                        disabled={inFlight}
                        title={inFlight ? 'A run is already in progress' : 'Run now'}
                      >
                        <Play className="h-3.5 w-3.5" aria-hidden />
                        Run
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => onEdit(report)}
                        title="Edit report"
                      >
                        <Pencil className="h-3.5 w-3.5" aria-hidden />
                        <span className="sr-only">Edit</span>
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => handleDelete(report)}
                        title="Delete report"
                      >
                        <Trash2 className="h-3.5 w-3.5 text-destructive-strong" aria-hidden />
                        <span className="sr-only">Delete</span>
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>,
                isOpen ? (
                  <TableRow key={`${report.id}-history`}>
                    <TableCell colSpan={8} className="bg-muted/30 p-0">
                      <RunHistory reportId={report.id} />
                    </TableCell>
                  </TableRow>
                ) : null,
              ]
            })}
          </TableBody>
        </Table>
      </TableContainer>
    </div>
  )
}
