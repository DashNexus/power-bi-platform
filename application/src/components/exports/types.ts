/**
 * Shared shapes for the exports feature.
 *
 * These mirror ExportScheduleResponse and ExportJobResponse in
 * `api/app/schemas/export.py`. A field added on one side without the other is
 * how a report silently stops carrying its source.
 */

/** Which database a report reads. Mirrors export_source.VALID_SOURCE_KINDS. */
export type ReportSourceKind = 'warehouse' | 'operations'

/** What started a run. Mirrors ExportJob.trigger_type. */
export type RunTrigger = 'manual' | 'schedule'

/** Lifecycle of one run. Mirrors ExportJob.status. */
export type RunStatus = 'pending' | 'running' | 'completed' | 'failed'

/** A SQL report definition — scheduled when cron_expression is set. */
export interface Report {
  id: number
  name: string
  format: string
  cron_expression: string | null
  is_active: boolean
  delivery_method: string
  delivery_config: Record<string, unknown> | null
  sql_query: string | null
  source_kind: ReportSourceKind
  warehouse_connection_id: number | null
  last_run_at: string | null
}

/** One execution of a report or a one-off export; also the run log entry. */
export interface ExportRun {
  id: number
  format: string
  status: RunStatus
  delivery_method: string
  name: string | null
  schedule_id: number | null
  source_kind: ReportSourceKind
  warehouse_connection_id: number | null
  trigger_type: RunTrigger
  row_count: number | null
  file_path: string | null
  file_name: string | null
  file_size_bytes: number | null
  /** Failure reason, or a warning on a run that otherwise succeeded. */
  error_message: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
  expires_at: string | null
}

/**
 * The run-log filters, as the UI holds them.
 *
 * Sent to the API as query parameters rather than applied in the browser: the
 * run log is paginated by a limit, so filtering the rows already fetched would
 * hide matches that are simply further down the table.
 */
export interface RunFilterState {
  search: string
  status: string
  triggerType: string
}

export const EMPTY_RUN_FILTERS: RunFilterState = { search: '', status: '', triggerType: '' }

/** True when at least one filter would narrow the run log. */
export function hasRunFilters(filters: RunFilterState): boolean {
  return Boolean(filters.search.trim() || filters.status || filters.triggerType)
}

/**
 * Build the query string for a filtered run-log request.
 *
 * Empty filters are omitted rather than sent blank: `status=` would reach the
 * API as an empty string, and the run-log endpoints reject a status no run can
 * have. `trigger_type` is snake_case to match `ExportJob.trigger_type`.
 */
export function runFilterParams(filters: RunFilterState, limit: number): string {
  const params = new URLSearchParams({ limit: String(limit) })
  const search = filters.search.trim()
  if (search) params.set('search', search)
  if (filters.status) params.set('status', filters.status)
  if (filters.triggerType) params.set('trigger_type', filters.triggerType)
  return params.toString()
}

/** Result of testing a report definition without saving it. */
export interface ReportPreview {
  columns: string[]
  rows: unknown[][]
  row_count: number
  truncated: boolean
  elapsed_ms: number
  source_kind: ReportSourceKind
}

/** Human-readable file size for a run's result. */
export function formatBytes(bytes: number | null): string {
  if (bytes === null || bytes < 0) return '—'
  if (bytes < 1024) return `${bytes} B`
  const units = ['KB', 'MB', 'GB']
  let value = bytes / 1024
  let unit = 0
  while (value >= 1024 && unit < units.length - 1) {
    value /= 1024
    unit += 1
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[unit]}`
}

/** Whole days until a stored result is purged, or null if it has none. */
export function daysUntilExpiry(expiresAt: string | null): number | null {
  if (!expiresAt) return null
  const ms = new Date(expiresAt).getTime() - Date.now()
  return Math.max(0, Math.ceil(ms / 86_400_000))
}

/**
 * Download a completed run's file.
 *
 * Not a plain link: the API is a separate origin behind Bearer auth, so the
 * bytes have to be fetched with the token and handed to the browser as an
 * object URL. `createClientFetch` parses JSON, which a spreadsheet is not.
 */
export async function downloadRun(run: ExportRun, accessToken: string): Promise<void> {
  const base = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
  const response = await fetch(`${base}/exports/jobs/${run.id}/content`, {
    headers: { Authorization: `Bearer ${accessToken}` },
  })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? 'The file could not be downloaded.')
  }

  const blob = await response.blob()
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = run.file_name ?? `export_${run.id}.${run.format}`
  document.body.appendChild(anchor)
  anchor.click()
  anchor.remove()
  // Revoking immediately can cancel the download in some browsers; a tick is
  // enough for the navigation to have started.
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}
