'use client'

/**
 * Result of testing a report query, shown inside the report editor.
 *
 * A test is a look at the data, not a run: the API fetches only the first rows
 * with a short timeout and stores nothing. This panel is therefore about
 * "is the query right", which means the column names, a few rows, and how long
 * it took — a query that is slow here will be slower on the full result set.
 */
import { Clock, Table2 } from 'lucide-react'
import type { ReportPreview } from '@/components/exports/types'
import { Alert } from '@/components/ui'

interface ReportPreviewPanelProps {
  preview: ReportPreview
}

/** Render a cell without letting one long value stretch the table. */
function cell(value: unknown): string {
  if (value === null || value === undefined) return '—'
  const text = String(value)
  return text.length > 60 ? `${text.slice(0, 60)}…` : text
}

// A slow test means a slower run. Warn rather than fail: the query may be
// legitimately expensive, and the person is the one who can judge that.
const SLOW_MS = 5000

export function ReportPreviewPanel({ preview }: ReportPreviewPanelProps) {
  if (preview.columns.length === 0) {
    return <Alert tone="warning">The query ran but returned no columns.</Alert>
  }

  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted/30 p-3">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        <span className="inline-flex items-center gap-1.5 font-medium text-foreground">
          <Table2 className="h-3.5 w-3.5" aria-hidden />
          {preview.row_count === 0
            ? 'No rows'
            : `${preview.row_count} row${preview.row_count === 1 ? '' : 's'}`}
          {preview.truncated && ' shown'}
        </span>
        <span>
          {preview.columns.length} column
          {preview.columns.length === 1 ? '' : 's'}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Clock className="h-3.5 w-3.5" aria-hidden />
          {preview.elapsed_ms.toLocaleString()} ms
        </span>
        <span>
          {preview.source_kind === 'operations' ? 'Operations database' : 'Warehouse connection'}
        </span>
      </div>

      {preview.row_count === 0 && (
        <Alert tone="warning">
          The query is valid but matched nothing. A scheduled report would deliver an empty file.
        </Alert>
      )}

      {preview.elapsed_ms > SLOW_MS && (
        <Alert tone="warning">
          This took {(preview.elapsed_ms / 1000).toFixed(1)}s for only the first rows. The full run
          will take longer — consider narrowing it before scheduling.
        </Alert>
      )}

      {preview.rows.length > 0 && (
        // Its own scroll container: a wide result must not widen the dialog.
        <div className="max-h-56 overflow-auto rounded border border-border bg-card">
          <table className="w-full text-xs">
            <thead className="sticky top-0 bg-muted">
              <tr>
                {preview.columns.map(column => (
                  <th
                    key={column}
                    className="whitespace-nowrap px-2 py-1.5 text-left font-medium text-foreground"
                  >
                    {column}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {preview.rows.map((row, rowIndex) => (
                // A result row has no identity of its own, and the whole list is
                // replaced on every test, so the index is a stable enough key.
                <tr key={rowIndex} className="border-t border-border">
                  {row.map((value, cellIndex) => (
                    <td
                      key={preview.columns[cellIndex] ?? cellIndex}
                      className="whitespace-nowrap px-2 py-1 text-muted-foreground"
                    >
                      {cell(value)}
                    </td>
                  ))}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {preview.truncated && (
        <p className="text-xs text-muted-foreground">
          More rows matched than are shown here. The full run exports all of them, up to the
          configured ceiling.
        </p>
      )}
    </div>
  )
}
