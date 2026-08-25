'use client'

/**
 * Condition checks for a pipeline connection: pipeline-idle and data-freshness
 * alerts, evaluated by the poller independently of the run-notification switch.
 *
 * Conditions alert on state transitions only (once when they trip, once on
 * recovery), so a persistent problem never re-alerts every check cycle.
 */
import { useCallback, useEffect, useState } from 'react'
import { toast } from 'sonner'
import { Activity, Clock, Database, Loader2, Pencil, Play, Plus, Trash2 } from 'lucide-react'
import type { createClientFetch } from '@/lib/api'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import { Field, Input, Select } from '@/components/ui/Input'
import { Alert, LoadingRows } from '@/components/ui/Feedback'
import { Modal } from '@/components/ui/Modal'
import { Toggle, ToggleRow } from '@/components/ui/Toggle'
import { NotificationGroupPicker } from './NotificationGroupPicker'
import { MessageTemplateEditor } from './MessageTemplateEditor'
import {
  CONDITION_PLACEHOLDERS,
  POLL_OPTIONS,
  UNIT_MINUTES,
  conditionSummary,
  conditionToPayload,
  formatDuration,
  splitThreshold,
  type ConditionCheckResult,
  type ConditionPayload,
  type ConditionType,
  type NotificationCondition,
  type NotificationGroup,
  type ThresholdUnit,
  type WarehouseOption,
} from './notificationTypes'

function ConditionStatus({ condition }: { condition: NotificationCondition }) {
  if (condition.is_triggered) return <Badge tone="danger">Triggered</Badge>
  if (condition.last_error) {
    return (
      <Badge tone="warning" title={condition.last_error} className="cursor-help">
        Check error
      </Badge>
    )
  }
  if (condition.last_checked_at) return <Badge tone="success">OK</Badge>
  return <Badge tone="neutral">Not checked yet</Badge>
}

interface ConditionFormState {
  name: string
  condition_type: ConditionType
  enabled: boolean
  thresholdValue: number
  thresholdUnit: ThresholdUnit
  check_frequency_minutes: number
  pipeline_name: string | null
  warehouse_connection_id: number | null
  schema_name: string
  table_name: string
  timestamp_column: string
  group_ids: number[]
  message_template: string
  notify_on_recovery: boolean
}

function emptyForm(): ConditionFormState {
  return {
    name: '',
    condition_type: 'pipeline_idle',
    enabled: true,
    thresholdValue: 6,
    thresholdUnit: 'hours',
    check_frequency_minutes: 60,
    pipeline_name: null,
    warehouse_connection_id: null,
    schema_name: '',
    table_name: '',
    timestamp_column: '',
    group_ids: [],
    message_template: '',
    notify_on_recovery: true,
  }
}

function toForm(c: NotificationCondition): ConditionFormState {
  const { value, unit } = splitThreshold(c.threshold_minutes)
  return {
    name: c.name,
    condition_type: c.condition_type,
    enabled: c.enabled,
    thresholdValue: value,
    thresholdUnit: unit,
    check_frequency_minutes: c.check_frequency_minutes,
    pipeline_name: c.pipeline_name,
    warehouse_connection_id: c.warehouse_connection_id,
    schema_name: c.schema_name ?? '',
    table_name: c.table_name ?? '',
    timestamp_column: c.timestamp_column ?? '',
    group_ids: c.group_ids,
    message_template: c.message_template,
    notify_on_recovery: c.notify_on_recovery,
  }
}

interface ConditionFormProps {
  initial: NotificationCondition | null
  pipelines: string[]
  groups: NotificationGroup[]
  warehouses: WarehouseOption[]
  saving: boolean
  onSave: (payload: ConditionPayload) => void
  onCancel: () => void
}

function ConditionForm({
  initial,
  pipelines,
  groups,
  warehouses,
  saving,
  onSave,
  onCancel,
}: ConditionFormProps) {
  const [form, setForm] = useState<ConditionFormState>(() =>
    initial ? toForm(initial) : emptyForm(),
  )
  const [errors, setErrors] = useState<Record<string, string>>({})
  const isFreshness = form.condition_type === 'data_freshness'

  function patch(p: Partial<ConditionFormState>) {
    setForm(prev => ({ ...prev, ...p }))
  }

  function handleSubmit() {
    const next: Record<string, string> = {}
    if (!form.name.trim()) next.name = 'Give the check a name so alerts are identifiable.'
    if (!Number.isFinite(form.thresholdValue) || form.thresholdValue < 1) {
      next.threshold = 'Threshold must be at least 1.'
    }
    if (isFreshness) {
      if (!form.table_name.trim()) next.table = 'Table is required for a freshness check.'
      if (!form.timestamp_column.trim()) next.column = 'Timestamp column is required.'
    }
    setErrors(next)
    if (Object.keys(next).length > 0) return

    onSave({
      name: form.name.trim(),
      condition_type: form.condition_type,
      enabled: form.enabled,
      threshold_minutes: Math.round(form.thresholdValue) * UNIT_MINUTES[form.thresholdUnit],
      check_frequency_minutes: form.check_frequency_minutes,
      pipeline_name: isFreshness ? null : form.pipeline_name,
      warehouse_connection_id: isFreshness ? form.warehouse_connection_id : null,
      schema_name: isFreshness ? form.schema_name.trim() || null : null,
      table_name: isFreshness ? form.table_name.trim() : null,
      timestamp_column: isFreshness ? form.timestamp_column.trim() : null,
      group_ids: form.group_ids,
      message_template: form.message_template,
      notify_on_recovery: form.notify_on_recovery,
    })
  }

  const thresholdMinutes =
    Math.round(form.thresholdValue || 0) * UNIT_MINUTES[form.thresholdUnit]

  return (
    <Modal
      open
      onClose={onCancel}
      size="lg"
      title={initial ? `Edit ${initial.name}` : 'New condition check'}
      description={
        isFreshness
          ? 'Alerts when a warehouse table stops receiving fresh rows.'
          : 'Alerts when a pipeline stops running.'
      }
      footer={
        <>
          <Button variant="outline" onClick={onCancel}>
            Cancel
          </Button>
          <Button onClick={handleSubmit} isLoading={saving}>
            {initial ? 'Save Check' : 'Create Check'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Name" htmlFor="cond-name" required error={errors.name}>
            <Input
              id="cond-name"
              value={form.name}
              onChange={e => patch({ name: e.target.value })}
              placeholder="Orders table freshness"
              invalid={!!errors.name}
            />
          </Field>
          <Field label="Check type" htmlFor="cond-type">
            <Select
              id="cond-type"
              value={form.condition_type}
              onChange={e => patch({ condition_type: e.target.value as ConditionType })}
            >
              <option value="pipeline_idle">Pipeline has not run</option>
              <option value="data_freshness">Data freshness</option>
            </Select>
          </Field>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field
            label="Alert when older than"
            error={errors.threshold}
            hint={thresholdMinutes > 0 ? `= ${formatDuration(thresholdMinutes)}` : undefined}
          >
            <div className="flex gap-2">
              <Input
                type="number"
                min={1}
                value={form.thresholdValue}
                onChange={e => patch({ thresholdValue: Number(e.target.value) })}
                aria-label="Threshold amount"
                invalid={!!errors.threshold}
                className="w-24"
              />
              <Select
                value={form.thresholdUnit}
                onChange={e => patch({ thresholdUnit: e.target.value as ThresholdUnit })}
                aria-label="Threshold unit"
              >
                <option value="minutes">minutes</option>
                <option value="hours">hours</option>
                <option value="days">days</option>
              </Select>
            </div>
          </Field>
          <Field label="Check frequency" htmlFor="cond-freq">
            <Select
              id="cond-freq"
              value={form.check_frequency_minutes}
              onChange={e => patch({ check_frequency_minutes: Number(e.target.value) })}
            >
              {POLL_OPTIONS.map(o => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        {isFreshness ? (
          <>
            <Field label="Warehouse" htmlFor="cond-wh">
              <Select
                id="cond-wh"
                value={form.warehouse_connection_id ?? ''}
                onChange={e =>
                  patch({
                    warehouse_connection_id: e.target.value === '' ? null : Number(e.target.value),
                  })
                }
              >
                <option value="">Default warehouse (marts)</option>
                {warehouses.map(w => (
                  <option key={w.id} value={w.id}>
                    {w.name}
                  </option>
                ))}
              </Select>
            </Field>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Schema" htmlFor="cond-schema">
                <Input
                  id="cond-schema"
                  value={form.schema_name}
                  onChange={e => patch({ schema_name: e.target.value })}
                  placeholder={form.warehouse_connection_id === null ? 'marts' : 'public'}
                />
              </Field>
              <Field label="Table" htmlFor="cond-table" required error={errors.table}>
                <Input
                  id="cond-table"
                  value={form.table_name}
                  onChange={e => patch({ table_name: e.target.value })}
                  placeholder="fct_orders"
                  invalid={!!errors.table}
                />
              </Field>
              <Field label="Timestamp column" htmlFor="cond-col" required error={errors.column}>
                <Input
                  id="cond-col"
                  value={form.timestamp_column}
                  onChange={e => patch({ timestamp_column: e.target.value })}
                  placeholder="updated_at"
                  invalid={!!errors.column}
                />
              </Field>
            </div>
          </>
        ) : (
          <Field
            label="Pipeline"
            htmlFor="cond-pipeline"
            hint="Any pipeline means a run of anything on this connection resets the timer."
          >
            <Select
              id="cond-pipeline"
              value={form.pipeline_name ?? ''}
              onChange={e => patch({ pipeline_name: e.target.value === '' ? null : e.target.value })}
            >
              <option value="">Any pipeline</option>
              {pipelines.map(name => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </Select>
          </Field>
        )}

        <NotificationGroupPicker
          label="Notification groups"
          groups={groups}
          selected={form.group_ids}
          onChange={v => patch({ group_ids: v })}
          warnWhenEmpty
        />

        <MessageTemplateEditor
          label="Custom message (optional)"
          hint="Leave blank to use the built-in wording for this check type."
          value={form.message_template}
          onChange={v => patch({ message_template: v })}
          placeholders={CONDITION_PLACEHOLDERS}
          rows={2}
        />

        <ToggleRow
          label="Notify on recovery"
          hint="Send a follow-up when the condition clears."
          checked={form.notify_on_recovery}
          onCheckedChange={v => patch({ notify_on_recovery: v })}
        />
      </div>
    </Modal>
  )
}

interface ConditionChecksSectionProps {
  connectionId: number
  apiFetch: ReturnType<typeof createClientFetch>
  groups: NotificationGroup[]
  pipelines: string[]
}

export function ConditionChecksSection({
  connectionId,
  apiFetch,
  groups,
  pipelines,
}: ConditionChecksSectionProps) {
  const [conditions, setConditions] = useState<NotificationCondition[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [warehouses, setWarehouses] = useState<WarehouseOption[] | null>(null)
  // 'new' opens the create form; a condition opens its edit form.
  const [editing, setEditing] = useState<NotificationCondition | 'new' | null>(null)
  const [saving, setSaving] = useState(false)
  const [checkingId, setCheckingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    setLoadError(null)
    try {
      setConditions(
        await apiFetch<NotificationCondition[]>(`/data-pipelines/${connectionId}/conditions`),
      )
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load condition checks.')
    } finally {
      setLoading(false)
    }
  }, [apiFetch, connectionId])

  useEffect(() => {
    void load()
  }, [load])

  function openForm(target: NotificationCondition | 'new') {
    setEditing(target)
    // Warehouses are only needed by the freshness form; fetch on first open.
    if (warehouses === null) {
      apiFetch<WarehouseOption[]>('/warehouses')
        .then(setWarehouses)
        .catch(() => setWarehouses([]))
    }
  }

  async function handleSave(payload: ConditionPayload) {
    setSaving(true)
    try {
      if (editing && editing !== 'new') {
        await apiFetch(`/notification-conditions/${editing.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        })
        toast.success('Condition check updated.')
      } else {
        await apiFetch(`/data-pipelines/${connectionId}/conditions`, {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        toast.success('Condition check created.')
      }
      setEditing(null)
      void load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save condition check.')
    } finally {
      setSaving(false)
    }
  }

  async function handleToggle(c: NotificationCondition) {
    // Optimistic: the switch should respond immediately, not after a round trip.
    setConditions(prev => prev.map(x => (x.id === c.id ? { ...x, enabled: !x.enabled } : x)))
    try {
      await apiFetch(`/notification-conditions/${c.id}`, {
        method: 'PUT',
        body: JSON.stringify({ ...conditionToPayload(c), enabled: !c.enabled }),
      })
    } catch (err) {
      setConditions(prev => prev.map(x => (x.id === c.id ? { ...x, enabled: c.enabled } : x)))
      toast.error(err instanceof Error ? err.message : 'Failed to update condition check.')
    }
  }

  async function handleDelete(c: NotificationCondition) {
    if (!confirm(`Delete "${c.name}"? This cannot be undone.`)) return
    try {
      await apiFetch(`/notification-conditions/${c.id}`, { method: 'DELETE' })
      toast.success('Condition check deleted.')
      void load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete condition check.')
    }
  }

  async function handleCheck(c: NotificationCondition) {
    setCheckingId(c.id)
    try {
      const result = await apiFetch<ConditionCheckResult>(
        `/notification-conditions/${c.id}/check`,
        { method: 'POST' },
      )
      if (!result.ok) {
        toast.error(`Check failed: ${result.error ?? 'unknown error'}`)
      } else {
        const age =
          result.age_minutes !== null ? formatDuration(Math.round(result.age_minutes)) : null
        if (result.triggered) {
          const detail =
            c.condition_type === 'pipeline_idle'
              ? age
                ? `no runs in ${age}`
                : 'no runs found'
              : age
                ? `newest data ${age} old`
                : 'no data found'
          toast.warning(`Would alert — ${detail}`)
        } else {
          const detail =
            c.condition_type === 'pipeline_idle'
              ? age
                ? `last run ${age} ago`
                : null
              : age
                ? `newest data ${age} old`
                : null
          toast.success(detail ? `Healthy — ${detail}` : 'Healthy')
        }
      }
      void load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Check failed.')
    } finally {
      setCheckingId(null)
    }
  }

  const triggeredCount = conditions.filter(c => c.is_triggered && c.enabled).length

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start justify-between gap-4">
          <div className="flex min-w-0 items-start gap-3">
            <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-success-subtle text-success-strong">
              <Activity className="h-4 w-4" aria-hidden />
            </span>
            <div className="min-w-0">
              <CardTitle className="flex flex-wrap items-center gap-2">
                Condition checks
                {triggeredCount > 0 && (
                  <Badge tone="danger">
                    {triggeredCount} triggered
                  </Badge>
                )}
              </CardTitle>
              <CardDescription>
                Alert when a pipeline goes quiet or warehouse data goes stale. These run even when
                run notifications are switched off, and alert once on trip and once on recovery.
              </CardDescription>
            </div>
          </div>
          <Button variant="outline" size="sm" onClick={() => openForm('new')} className="shrink-0">
            <Plus aria-hidden />
            Add Check
          </Button>
        </div>
      </CardHeader>

      <CardContent className="space-y-2">
        {loadError && <Alert tone="danger">{loadError}</Alert>}

        {loading ? (
          <LoadingRows rows={2} />
        ) : conditions.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
            No condition checks yet. Add one to be told when a pipeline stops running or a table
            stops updating — neither of which produces a failed run to alert on.
          </p>
        ) : (
          conditions.map(c => (
            <div
              key={c.id}
              className="rounded-xl border border-border bg-card p-3.5 transition-colors hover:border-border-strong"
            >
              <div className="flex items-start gap-3">
                <span
                  title={
                    c.condition_type === 'pipeline_idle'
                      ? 'Pipeline idle check'
                      : 'Data freshness check'
                  }
                  className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-info-strong"
                >
                  {c.condition_type === 'pipeline_idle' ? (
                    <Clock className="h-4 w-4" aria-hidden />
                  ) : (
                    <Database className="h-4 w-4" aria-hidden />
                  )}
                </span>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-2">
                    <span
                      className={
                        c.enabled
                          ? 'truncate text-sm font-medium text-foreground'
                          : 'truncate text-sm font-medium text-muted-foreground'
                      }
                    >
                      {c.name}
                    </span>
                    <ConditionStatus condition={c} />
                    {!c.enabled && <Badge tone="neutral">Disabled</Badge>}
                    {c.group_ids.length === 0 && <Badge tone="warning">No recipients</Badge>}
                  </div>
                  <p className="mt-0.5 text-xs text-muted-foreground">{conditionSummary(c)}</p>
                  {c.last_checked_at && (
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Last checked {new Date(c.last_checked_at).toLocaleString()}
                    </p>
                  )}
                  {c.last_error && (
                    <p className="mt-1 text-xs text-destructive-strong">{c.last_error}</p>
                  )}
                </div>

                <div className="flex shrink-0 items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="Run this check now (dry run — sends nothing)"
                    aria-label={`Run ${c.name} now`}
                    onClick={() => void handleCheck(c)}
                    disabled={checkingId !== null}
                  >
                    {checkingId === c.id ? (
                      <Loader2 className="animate-spin" aria-hidden />
                    ) : (
                      <Play aria-hidden />
                    )}
                  </Button>
                  <span className="px-1" title={c.enabled ? 'Disable' : 'Enable'}>
                    <Toggle
                      checked={c.enabled}
                      onCheckedChange={() => void handleToggle(c)}
                      ariaLabel={c.enabled ? `Disable ${c.name}` : `Enable ${c.name}`}
                    />
                  </span>
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    title="Edit"
                    aria-label={`Edit ${c.name}`}
                    onClick={() => openForm(c)}
                  >
                    <Pencil aria-hidden />
                  </Button>
                  <Button
                    variant="destructive-ghost"
                    size="icon-sm"
                    title="Delete"
                    aria-label={`Delete ${c.name}`}
                    onClick={() => void handleDelete(c)}
                  >
                    <Trash2 aria-hidden />
                  </Button>
                </div>
              </div>
            </div>
          ))
        )}
      </CardContent>

      {editing && (
        <ConditionForm
          key={editing === 'new' ? 'new' : editing.id}
          initial={editing === 'new' ? null : editing}
          pipelines={pipelines}
          groups={groups}
          warehouses={warehouses ?? []}
          saving={saving}
          onSave={payload => void handleSave(payload)}
          onCancel={() => setEditing(null)}
        />
      )}
    </Card>
  )
}
