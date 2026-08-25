'use client'

/**
 * Modal that previews a change's previous and current state side by side.
 *
 * Renders the ledger entry's before/after snapshots as field tables with changed
 * fields highlighted. Handles create (no previous) and delete (no current).
 */
import { X, ArrowRight } from 'lucide-react'
import type { ChangeRecord } from './types'

interface StatePreviewProps {
  record: ChangeRecord
  onClose: () => void
}

function formatValue(v: unknown): string {
  if (v === null || v === undefined) return '—'
  if (typeof v === 'object') return JSON.stringify(v, null, 2)
  return String(v)
}

function StateColumn({
  title,
  state,
  changedFields,
  emptyLabel,
}: {
  title: string
  state: Record<string, unknown> | null
  changedFields: Set<string>
  emptyLabel: string
}) {
  return (
    <div className="min-w-0 flex-1">
      <p className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">{title}</p>
      {state === null ? (
        <p className="rounded-lg border border-dashed border-border-strong py-8 text-center text-sm text-muted-foreground ">
          {emptyLabel}
        </p>
      ) : (
        <dl className="space-y-1 rounded-lg border border-border p-3 text-sm ">
          {Object.entries(state).map(([k, v]) => (
            <div
              key={k}
              className={`flex gap-2 rounded px-1 py-0.5 ${
 changedFields.has(k) ? 'bg-warning-subtle ' : ''
 }`}
            >
              <dt className="w-32 shrink-0 truncate font-medium text-muted-foreground ">
                {k}
              </dt>
              <dd className="min-w-0 flex-1 whitespace-pre-wrap break-words text-foreground ">
                {formatValue(v)}
              </dd>
            </div>
          ))}
        </dl>
      )}
    </div>
  )
}

export function StatePreview({ record, onClose }: StatePreviewProps) {
  const changed = new Set(record.diff.map(d => d.field))

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 p-4"
      onClick={onClose}
    >
      <div
        className="flex max-h-[85vh] w-full max-w-4xl flex-col rounded-xl bg-card shadow-xl "
        onClick={e => e.stopPropagation()}
      >
        <div className="flex items-center justify-between border-b border-border px-5 py-3 ">
          <div>
            <h3 className="text-sm font-semibold text-foreground ">
              {record.action.charAt(0).toUpperCase() + record.action.slice(1)}:{' '}
              {record.resource_name ?? `${record.resource_type} #${record.resource_id}`}
            </h3>
            <p className="text-xs text-muted-foreground">
              {record.source === 'ai' ? 'AI' : record.actor_name ?? 'User'} ·{' '}
              {new Date(record.created_at).toLocaleString()}
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="Close"
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground "
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="flex items-stretch gap-4 overflow-y-auto p-5">
          <StateColumn
            title="Previous"
            state={record.before}
            changedFields={changed}
            emptyLabel="No previous state (created)"
          />
          <div className="flex items-center text-muted-foreground">
            <ArrowRight className="h-5 w-5" />
          </div>
          <StateColumn
            title="Current"
            state={record.after}
            changedFields={changed}
            emptyLabel="No current state (deleted)"
          />
        </div>
      </div>
    </div>
  )
}
