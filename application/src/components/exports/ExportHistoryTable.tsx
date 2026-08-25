'use client'

/**
 * The run log: every export execution, newest first.
 *
 * One row per run — scheduled or manual, succeeded or failed. Rows and their
 * stored files are kept for 30 days and then purged by the export worker, so
 * this table is a complete record of that window and nothing older.
 */
import { useCallback, useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Download, History } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { RunFilters } from '@/components/exports/RunFilters'
import {
  EMPTY_RUN_FILTERS,
  daysUntilExpiry,
  downloadRun,
  formatBytes,
  hasRunFilters,
  runFilterParams,
  type ExportRun,
  type RunFilterState,
} from '@/components/exports/types'
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

const TERMINAL = new Set(['completed', 'failed'])
const POLL_MS = 4000
const PAGE_SIZE = 100

export function ExportHistoryTable() {
  const { data: session } = useSession()
  const token = session?.user?.access_token
  const [runs, setRuns] = useState<ExportRun[]>([])
  const [filters, setFilters] = useState<RunFilterState>(EMPTY_RUN_FILTERS)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const load = useCallback(async () => {
    if (!token) return
    try {
      const apiFetch = createClientFetch(token)
      setRuns(await apiFetch<ExportRun[]>(`/exports/jobs?${runFilterParams(filters, PAGE_SIZE)}`))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the run log.')
    } finally {
      setLoading(false)
    }
  }, [token, filters])

  useEffect(() => {
    load()
  }, [load])

  // Poll only while a run is in flight; a settled log does not change on its own.
  const hasActiveRun = runs.some(run => !TERMINAL.has(run.status))
  useEffect(() => {
    if (!hasActiveRun) return
    const id = setInterval(load, POLL_MS)
    return () => clearInterval(id)
  }, [hasActiveRun, load])

  async function handleDownload(run: ExportRun) {
    if (!token) return
    try {
      await downloadRun(run, token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The file could not be downloaded.')
    }
  }

  const filtered = hasRunFilters(filters)

  return (
    <div className="space-y-3">
      {/* Rendered above every state, empty included: a filter that matches
          nothing must not take away the control that clears it. */}
      <RunFilters
        value={filters}
        onChange={setFilters}
        searchPlaceholder="Search by report, format, or error…"
        resultCount={runs.length}
      />

      {error && <Alert tone="danger">{error}</Alert>}

      {loading ? (
        <LoadingRows />
      ) : runs.length === 0 ? (
        <EmptyState
          icon={History}
          title={filtered ? 'No runs match these filters' : 'Nothing has run yet'}
          description={
            filtered
              ? 'Nothing in the retained run log matches the current search. Widen or clear the filters to see more.'
              : 'Runs appear here once a report is executed, whether on a schedule or on demand. They are kept for 30 days.'
          }
          action={
            filtered ? (
              <Button variant="outline" onClick={() => setFilters(EMPTY_RUN_FILTERS)}>
                Clear filters
              </Button>
            ) : undefined
          }
        />
      ) : (
        <TableContainer>
          <Table>
            <TableHead>
              <TableRow>
                <TableHeaderCell>Report</TableHeaderCell>
                <TableHeaderCell>Status</TableHeaderCell>
                <TableHeaderCell>Trigger</TableHeaderCell>
                <TableHeaderCell>Rows</TableHeaderCell>
                <TableHeaderCell>Size</TableHeaderCell>
                <TableHeaderCell>Started</TableHeaderCell>
                <TableHeaderCell>Result</TableHeaderCell>
                <TableHeaderCell className="text-right">Actions</TableHeaderCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {runs.map(run => {
                const expiresIn = daysUntilExpiry(run.expires_at)
                return (
                  <TableRow key={run.id}>
                    <TableCell>
                      <span className="font-medium text-foreground">
                        {run.name ?? `Export #${run.id}`}
                      </span>
                      <span className="ml-2 text-xs uppercase text-muted-foreground">
                        {run.format}
                      </span>
                      {run.error_message && (
                        <p
                          className={`mt-0.5 text-xs ${
                            run.status === 'failed'
                              ? 'text-destructive-strong'
                              : 'text-muted-foreground'
                          }`}
                        >
                          {run.error_message}
                        </p>
                      )}
                    </TableCell>
                    <TableCell>
                      <StatusBadge status={run.status} />
                    </TableCell>
                    <TableCell>
                      <Badge tone="neutral">
                        {run.trigger_type === 'schedule' ? 'Scheduled' : 'Manual'}
                      </Badge>
                    </TableCell>
                    <TableCell muted>{run.row_count?.toLocaleString() ?? '—'}</TableCell>
                    <TableCell muted>{formatBytes(run.file_size_bytes)}</TableCell>
                    <TableCell muted>
                      {new Date(run.started_at ?? run.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell muted>
                      {run.status !== 'completed'
                        ? '—'
                        : expiresIn === null
                          ? 'Stored'
                          : expiresIn === 0
                            ? 'Expires today'
                            : `Expires in ${expiresIn}d`}
                    </TableCell>
                    <TableCell className="text-right">
                      {run.status === 'completed' && run.file_path ? (
                        <Button variant="ghost" size="sm" onClick={() => handleDownload(run)}>
                          <Download className="h-3.5 w-3.5" aria-hidden />
                          Download
                        </Button>
                      ) : null}
                    </TableCell>
                  </TableRow>
                )
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </div>
  )
}
