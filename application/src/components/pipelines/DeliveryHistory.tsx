'use client'

/**
 * Delivery history for a pipeline connection's notifications.
 *
 * Answers the question the feature could not previously answer at all: did the
 * alert go out, to which destinations, and if it failed, why. Rows expand to the
 * per-destination outcome and the exact message body that was sent.
 *
 * Webhook targets arrive already redacted from the API — the URL is the
 * credential, so it is never stored or shown in full.
 */
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  AlertTriangle,
  CheckCircle2,
  ChevronDown,
  ChevronRight,
  Inbox,
  RefreshCw,
} from 'lucide-react'
import type { createClientFetch } from '@/lib/api'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Alert, LoadingRows } from '@/components/ui/Feedback'
import { EmptyState } from '@/components/ui/EmptyState'
import { Select } from '@/components/ui/Input'
import { SectionHeader } from '@/components/ui/PageHeader'
import { cn } from '@/lib/utils'
import {
  CHANNEL_LABELS,
  SOURCE_LABELS,
  type DeliverySummary,
  type NotificationDelivery,
} from './notificationTypes'

type StatusFilter = 'all' | 'sent' | 'failed'

const SOURCE_TONES: Record<string, 'success' | 'danger' | 'warning' | 'info' | 'neutral'> = {
  run_success: 'success',
  run_failure: 'danger',
  condition_trigger: 'warning',
  condition_recovery: 'success',
  test: 'info',
}

interface DeliveryHistoryProps {
  connectionId: number
  apiFetch: ReturnType<typeof createClientFetch>
}

function DeliveryRow({ delivery }: { delivery: NotificationDelivery }) {
  const [open, setOpen] = useState(false)
  const failed = delivery.failed_count > 0
  const total = delivery.sent_count + delivery.failed_count

  return (
    <div className="border-b border-border last:border-0">
      <button
        type="button"
        onClick={() => setOpen(o => !o)}
        aria-expanded={open}
        className="flex w-full items-start gap-2.5 px-3 py-2.5 text-left transition-colors hover:bg-accent"
      >
        {open ? (
          <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        ) : (
          <ChevronRight className="mt-0.5 h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
        )}

        <span className="min-w-0 flex-1">
          <span className="flex flex-wrap items-center gap-2">
            <Badge tone={SOURCE_TONES[delivery.source] ?? 'neutral'}>
              {SOURCE_LABELS[delivery.source] ?? delivery.source}
            </Badge>
            {delivery.pipeline_name && (
              <span className="truncate text-sm font-medium text-foreground">
                {delivery.pipeline_name}
              </span>
            )}
          </span>
          <span className="mt-0.5 block truncate text-xs text-muted-foreground">
            {delivery.subject}
          </span>
        </span>

        <span className="flex shrink-0 items-center gap-2">
          {failed ? (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-destructive-strong">
              <AlertTriangle className="h-3.5 w-3.5" aria-hidden />
              {delivery.failed_count}/{total} failed
            </span>
          ) : (
            <span className="inline-flex items-center gap-1 text-xs font-medium text-success-strong">
              <CheckCircle2 className="h-3.5 w-3.5" aria-hidden />
              {delivery.sent_count} sent
            </span>
          )}
          <span className="hidden whitespace-nowrap text-xs text-muted-foreground sm:inline">
            {delivery.created_at ? new Date(delivery.created_at).toLocaleString() : '—'}
          </span>
        </span>
      </button>

      {open && (
        <div className="space-y-3 bg-muted/40 px-9 py-3">
          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Message sent
            </p>
            <p className="whitespace-pre-wrap break-words rounded-lg border border-border bg-card p-2.5 text-sm text-foreground">
              {delivery.message || <span className="italic text-muted-foreground">(empty)</span>}
            </p>
          </div>

          <div>
            <p className="mb-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Destinations
            </p>
            {delivery.details.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No destinations were configured at the time of sending.
              </p>
            ) : (
              <ul className="space-y-1">
                {delivery.details.map((d, i) => (
                  <li
                    key={`${d.channel}-${i}`}
                    className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-card px-2.5 py-1.5"
                  >
                    <Badge tone={d.ok ? 'success' : 'danger'}>
                      {CHANNEL_LABELS[d.channel] ?? d.channel}
                    </Badge>
                    <span className="min-w-0 flex-1 truncate font-mono text-xs text-muted-foreground">
                      {d.target}
                    </span>
                    {d.error && (
                      <span className="w-full text-xs text-destructive-strong">{d.error}</span>
                    )}
                  </li>
                ))}
              </ul>
            )}
          </div>

          {(delivery.run_id || delivery.created_at) && (
            <p className="text-xs text-muted-foreground">
              {delivery.created_at && <>Sent {new Date(delivery.created_at).toLocaleString()}</>}
              {delivery.run_id && (
                <>
                  {' · '}
                  Run <span className="font-mono">{delivery.run_id}</span>
                </>
              )}
            </p>
          )}
        </div>
      )}
    </div>
  )
}

export function DeliveryHistory({ connectionId, apiFetch }: DeliveryHistoryProps) {
  const [deliveries, setDeliveries] = useState<NotificationDelivery[]>([])
  const [summary, setSummary] = useState<DeliverySummary | null>(null)
  const [loading, setLoading] = useState(true)
  const [refreshing, setRefreshing] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [status, setStatus] = useState<StatusFilter>('all')
  const [source, setSource] = useState('all')

  const load = useCallback(async () => {
    setError(null)
    try {
      const params: Record<string, string | number> = { limit: 100, status }
      if (source !== 'all') params.source = source
      const [list, sum] = await Promise.all([
        apiFetch<{ deliveries: NotificationDelivery[] }>(
          `/data-pipelines/${connectionId}/notification-deliveries`,
          { searchParams: params },
        ),
        apiFetch<DeliverySummary>(`/data-pipelines/${connectionId}/notification-summary`, {
          searchParams: { days: 7 },
        }).catch(() => null),
      ])
      setDeliveries(list.deliveries ?? [])
      setSummary(sum)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load delivery history.')
      setDeliveries([])
    } finally {
      setLoading(false)
    }
  }, [apiFetch, connectionId, status, source])

  useEffect(() => {
    void load()
  }, [load])

  async function handleRefresh() {
    setRefreshing(true)
    try {
      await load()
    } finally {
      setRefreshing(false)
    }
  }

  const sourceOptions = useMemo(
    () => Object.keys(summary?.by_source ?? {}).sort(),
    [summary],
  )

  return (
    <div className="space-y-4">
      <SectionHeader
        title="Delivery history"
        description="Every alert this connection has attempted to send, with the per-destination result. Retained for 30 days."
        actions={
          <Button variant="outline" size="sm" onClick={() => void handleRefresh()} disabled={refreshing}>
            <RefreshCw className={cn(refreshing && 'animate-spin')} aria-hidden />
            Refresh
          </Button>
        }
      />

      {summary && summary.attempts > 0 && (
        <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: 'Attempts', value: summary.attempts, tone: 'text-foreground' },
            { label: 'Delivered', value: summary.sent, tone: 'text-success-strong' },
            { label: 'Failed', value: summary.failed, tone: 'text-destructive-strong' },
          ].map(stat => (
            <div key={stat.label} className="rounded-xl border border-border bg-card px-3 py-2.5">
              <p className="text-xs text-muted-foreground">{stat.label}</p>
              <p className={cn('mt-0.5 text-lg font-semibold tabular-nums', stat.tone)}>
                {stat.value.toLocaleString()}
              </p>
            </div>
          ))}
          <div className="rounded-xl border border-border bg-card px-3 py-2.5">
            <p className="text-xs text-muted-foreground">Last alert</p>
            <p className="mt-0.5 truncate text-sm font-medium text-foreground">
              {summary.last_delivery_at
                ? new Date(summary.last_delivery_at).toLocaleString()
                : 'Never'}
            </p>
          </div>
        </div>
      )}

      <div className="flex flex-wrap items-center gap-2">
        <Select
          aria-label="Filter by outcome"
          value={status}
          onChange={e => setStatus(e.target.value as StatusFilter)}
          className="w-auto text-xs"
        >
          <option value="all">All outcomes</option>
          <option value="sent">Fully delivered</option>
          <option value="failed">Had failures</option>
        </Select>
        {sourceOptions.length > 1 && (
          <Select
            aria-label="Filter by trigger"
            value={source}
            onChange={e => setSource(e.target.value)}
            className="w-auto text-xs"
          >
            <option value="all">All triggers</option>
            {sourceOptions.map(s => (
              <option key={s} value={s}>
                {SOURCE_LABELS[s] ?? s}
              </option>
            ))}
          </Select>
        )}
        <span className="ml-auto text-xs text-muted-foreground">
          {deliveries.length} {deliveries.length === 1 ? 'record' : 'records'}
        </span>
      </div>

      {error && <Alert tone="danger">{error}</Alert>}

      {loading ? (
        <LoadingRows rows={4} />
      ) : deliveries.length === 0 ? (
        <EmptyState
          icon={Inbox}
          title={
            status !== 'all' || source !== 'all'
              ? 'No deliveries match these filters'
              : 'No alerts sent yet'
          }
          description={
            status !== 'all' || source !== 'all'
              ? 'Clear the filters to see the full history.'
              : 'Once a monitored run finishes or a condition trips, every send attempt is recorded here. Use Send test above to verify delivery now.'
          }
        />
      ) : (
        <div className="overflow-hidden rounded-xl border border-border bg-card">
          {deliveries.map(d => (
            <DeliveryRow key={d.id} delivery={d} />
          ))}
        </div>
      )}
    </div>
  )
}
