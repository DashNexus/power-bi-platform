'use client'

/**
 * Run log for one report.
 *
 * Every execution is recorded — scheduled or manual, succeeded or failed — and
 * kept, with its result, for 30 days. A row whose result has passed that window
 * still shows what happened; only the file is gone.
 */
import { useCallback, useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Ban, Download } from 'lucide-react'
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
import { Alert, Button, LoadingRows, StatusBadge } from '@/components/ui'

interface RunHistoryProps {
  reportId: number
}

const TERMINAL = new Set(['completed', 'failed'])
const PAGE_SIZE = 25

/** Wall-clock duration of a run, or null while it has not finished. */
function duration(run: ExportRun): string | null {
  if (!run.started_at || !run.completed_at) return null
  const ms = new Date(run.completed_at).getTime() - new Date(run.started_at).getTime()
  if (ms < 1000) return '<1s'
  if (ms < 60_000) return `${Math.round(ms / 1000)}s`
  return `${Math.floor(ms / 60_000)}m ${Math.round((ms % 60_000) / 1000)}s`
}

export function RunHistory({ reportId }: RunHistoryProps) {
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
      const query = runFilterParams(filters, PAGE_SIZE)
      setRuns(await apiFetch<ExportRun[]>(`/exports/reports/${reportId}/runs?${query}`))
      setError(null)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not load the run history.')
    } finally {
      setLoading(false)
    }
  }, [token, reportId, filters])

  useEffect(() => {
    load()
  }, [load])

  async function handleDownload(run: ExportRun) {
    if (!token) return
    try {
      await downloadRun(run, token)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'The file could not be downloaded.')
    }
  }

  async function handleCancel(runId: number) {
    if (!token) return
    try {
      const apiFetch = createClientFetch(token)
      await apiFetch<unknown>(`/exports/jobs/${runId}/cancel`, { method: 'POST' })
      await load()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not cancel the run.')
    }
  }

  const filtered = hasRunFilters(filters)

  return (
    <div className="space-y-2 px-4 py-3">
      <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
        Run history — results are kept for 30 days
      </p>

      <RunFilters
        value={filters}
        onChange={setFilters}
        searchPlaceholder="Search this report's runs…"
        resultCount={runs.length}
      />

      {error && <Alert tone="danger">{error}</Alert>}

      {/* The controls stay mounted through loading and empty states: a search
          that matches nothing must not remove the box used to undo it. */}
      {loading ? (
        <LoadingRows rows={2} />
      ) : runs.length === 0 ? (
        <p className="py-4 text-sm text-muted-foreground">
          {filtered
            ? 'No runs match these filters.'
            : 'This report has not run yet. Press Run to try it now.'}
        </p>
      ) : (
        <ul className="divide-y divide-border">
          {runs.map(run => {
            const expiresIn = daysUntilExpiry(run.expires_at)
            const isActive = !TERMINAL.has(run.status)
            return (
              <li key={run.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 text-sm">
                <StatusBadge status={run.status} />
                <span className="text-muted-foreground">
                  {new Date(run.created_at).toLocaleString()}
                </span>
                <span className="text-xs text-muted-foreground">
                  {run.trigger_type === 'schedule' ? 'Scheduled' : 'Manual'}
                </span>
                {duration(run) && (
                  <span className="text-xs text-muted-foreground">{duration(run)}</span>
                )}
                {run.row_count !== null && (
                  <span className="text-xs text-muted-foreground">
                    {run.row_count.toLocaleString()} rows
                  </span>
                )}
                {run.file_size_bytes !== null && (
                  <span className="text-xs text-muted-foreground">
                    {formatBytes(run.file_size_bytes)}
                  </span>
                )}

                <span className="ml-auto flex items-center gap-2">
                  {expiresIn !== null && run.status === 'completed' && (
                    <span className="text-xs text-muted-foreground">
                      {expiresIn === 0 ? 'Expires today' : `Expires in ${expiresIn}d`}
                    </span>
                  )}
                  {isActive && (
                    <Button variant="ghost" size="sm" onClick={() => handleCancel(run.id)}>
                      <Ban className="h-3.5 w-3.5" aria-hidden />
                      Cancel
                    </Button>
                  )}
                  {run.status === 'completed' && run.file_path && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => handleDownload(run)}
                      title={run.file_name ?? undefined}
                    >
                      <Download className="h-3.5 w-3.5" aria-hidden />
                      Download
                    </Button>
                  )}
                </span>

                {run.error_message && (
                  // Shown for a completed run as well: that is where truncation
                  // and delivery failures are reported.
                  <p
                    className={`w-full text-xs ${
                      run.status === 'failed' ? 'text-destructive-strong' : 'text-muted-foreground'
                    }`}
                  >
                    {run.error_message}
                  </p>
                )}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
