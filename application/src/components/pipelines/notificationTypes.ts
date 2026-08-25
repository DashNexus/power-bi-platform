/**
 * Shared types and formatting helpers for pipeline notification settings.
 *
 * Split out of PipelineNotificationsTab so the settings form, condition checks,
 * and delivery history can share one vocabulary instead of redeclaring it.
 */

export interface NotificationGroup {
  id: number
  name: string
  channels?: Record<string, unknown[]>
}

export interface PipelineOverride {
  notify_on_success?: boolean
  notify_on_failure?: boolean
  success_message?: string
  failure_message?: string
}

export interface NotifConfig {
  enabled: boolean
  notify_on_success: boolean
  notify_on_failure: boolean
  success_message: string
  failure_message: string
  poll_frequency_minutes: number
  success_group_ids: number[]
  failure_group_ids: number[]
  pipeline_overrides: Record<string, PipelineOverride>
  min_interval_minutes: number
  quiet_hours_start: number | null
  quiet_hours_end: number | null
  quiet_hours_tz: string
  quiet_hours_include_failures: boolean
  last_polled_at: string | null
  next_poll_due_at: string | null
}

export type ConditionType = 'pipeline_idle' | 'data_freshness'

export interface NotificationCondition {
  id: number
  pipeline_connection_id: number
  name: string
  condition_type: ConditionType
  enabled: boolean
  threshold_minutes: number
  check_frequency_minutes: number
  pipeline_name: string | null
  warehouse_connection_id: number | null
  schema_name: string | null
  table_name: string | null
  timestamp_column: string | null
  group_ids: number[]
  message_template: string
  notify_on_recovery: boolean
  is_triggered: boolean
  last_checked_at: string | null
  last_observed_at: string | null
  last_error: string | null
}

export type ConditionPayload = Omit<
  NotificationCondition,
  | 'id'
  | 'pipeline_connection_id'
  | 'is_triggered'
  | 'last_checked_at'
  | 'last_observed_at'
  | 'last_error'
>

export interface ConditionCheckResult {
  ok: boolean
  triggered: boolean | null
  observed_at: string | null
  age_minutes: number | null
  error: string | null
}

export interface WarehouseOption {
  id: number
  name: string
}

/** One recorded delivery attempt from the server's audit trail. */
export interface DeliveryDetail {
  channel: string
  target: string
  ok: boolean
  error: string | null
}

export type DeliverySource =
  | 'run_success'
  | 'run_failure'
  | 'condition_trigger'
  | 'condition_recovery'
  | 'test'

export interface NotificationDelivery {
  id: number
  source: DeliverySource | string
  pipeline_name: string | null
  run_id: string | null
  condition_id: number | null
  subject: string
  message: string
  group_ids: number[]
  sent_count: number
  failed_count: number
  details: DeliveryDetail[]
  created_at: string | null
}

export interface DeliverySummary {
  days: number
  by_source: Record<string, { attempts: number; sent: number; failed: number }>
  attempts: number
  sent: number
  failed: number
  last_delivery_at: string | null
}

export interface PreviewResult {
  subject: string
  message: string
  template: string
  used_sample: boolean
  run_id: string | null
  context: Record<string, string>
}

export const POLL_OPTIONS = [
  { value: 10, label: 'Every 10 minutes' },
  { value: 15, label: 'Every 15 minutes' },
  { value: 30, label: 'Every 30 minutes' },
  { value: 60, label: 'Every hour' },
  { value: 120, label: 'Every 2 hours' },
  { value: 240, label: 'Every 4 hours' },
  { value: 480, label: 'Every 8 hours' },
  { value: 720, label: 'Every 12 hours' },
  { value: 1440, label: 'Once a day' },
] as const

export const THROTTLE_OPTIONS = [
  { value: 0, label: 'No limit — alert on every run' },
  { value: 15, label: 'At most once every 15 minutes' },
  { value: 30, label: 'At most once every 30 minutes' },
  { value: 60, label: 'At most once an hour' },
  { value: 240, label: 'At most once every 4 hours' },
  { value: 1440, label: 'At most once a day' },
] as const

/** Placeholders available in run-alert templates. */
export const RUN_PLACEHOLDERS = [
  'pipeline',
  'connection',
  'provider',
  'status',
  'message',
  'run_id',
  'started_at',
  'ended_at',
  'duration',
  'duration_ms',
  'invoked_by',
  'invoked_by_type',
  'parent_run_id',
] as const

export const CONDITION_PLACEHOLDERS = [
  'name',
  'scope',
  'pipeline',
  'table',
  'column',
  'age',
  'threshold',
  'observed_at',
] as const

export const SOURCE_LABELS: Record<string, string> = {
  run_success: 'Run succeeded',
  run_failure: 'Run failed',
  condition_trigger: 'Condition tripped',
  condition_recovery: 'Condition recovered',
  test: 'Test send',
}

export const CHANNEL_LABELS: Record<string, string> = {
  slack: 'Slack',
  teams: 'Teams',
  gchat: 'Google Chat',
  email: 'Email',
  sms: 'SMS',
}

export type ThresholdUnit = 'minutes' | 'hours' | 'days'

export const UNIT_MINUTES: Record<ThresholdUnit, number> = {
  minutes: 1,
  hours: 60,
  days: 1440,
}

/** Format a minute count as a compact duration, e.g. 90 → "1h 30m", 2880 → "2d". */
export function formatDuration(minutes: number): string {
  if (minutes >= 1440 && minutes % 1440 === 0) return `${minutes / 1440}d`
  if (minutes >= 60) {
    const h = Math.floor(minutes / 60)
    const m = minutes % 60
    return m === 0 ? `${h}h` : `${h}h ${m}m`
  }
  return `${minutes}m`
}

/** Split minutes into the largest whole unit, for the threshold inputs. */
export function splitThreshold(minutes: number): { value: number; unit: ThresholdUnit } {
  if (minutes >= 1440 && minutes % 1440 === 0) return { value: minutes / 1440, unit: 'days' }
  if (minutes >= 60 && minutes % 60 === 0) return { value: minutes / 60, unit: 'hours' }
  return { value: minutes, unit: 'minutes' }
}

/** Compact relative time: "3m ago", "in 12m", "just now". */
export function relativeTime(iso: string | null): string {
  if (!iso) return 'never'
  const then = new Date(iso).getTime()
  if (Number.isNaN(then)) return 'unknown'
  const deltaMinutes = Math.round((then - Date.now()) / 60000)
  const magnitude = Math.abs(deltaMinutes)
  if (magnitude < 1) return 'just now'
  const label = formatDuration(magnitude)
  return deltaMinutes < 0 ? `${label} ago` : `in ${label}`
}

export function conditionSummary(c: NotificationCondition): string {
  const freq =
    POLL_OPTIONS.find(o => o.value === c.check_frequency_minutes)?.label.toLowerCase() ??
    `every ${formatDuration(c.check_frequency_minutes)}`
  const threshold = formatDuration(c.threshold_minutes)
  if (c.condition_type === 'pipeline_idle') {
    const scope = c.pipeline_name ? `"${c.pipeline_name}" — no runs` : 'No runs'
    return `${scope} in ${threshold} — checks ${freq}`
  }
  return `${c.schema_name || 'marts'}.${c.table_name}.${c.timestamp_column} older than ${threshold} — checks ${freq}`
}

export function conditionToPayload(c: NotificationCondition): ConditionPayload {
  return {
    name: c.name,
    condition_type: c.condition_type,
    enabled: c.enabled,
    threshold_minutes: c.threshold_minutes,
    check_frequency_minutes: c.check_frequency_minutes,
    pipeline_name: c.pipeline_name,
    warehouse_connection_id: c.warehouse_connection_id,
    schema_name: c.schema_name,
    table_name: c.table_name,
    timestamp_column: c.timestamp_column,
    group_ids: c.group_ids,
    message_template: c.message_template,
    notify_on_recovery: c.notify_on_recovery,
  }
}

/**
 * Summarise a group's destinations, e.g. "Slack ×2 · Email ×3".
 *
 * Lets an operator confirm where alerts land without opening the groups admin.
 */
export function describeChannels(group: NotificationGroup): string {
  const parts = Object.entries(group.channels ?? {})
    .filter(([, list]) => Array.isArray(list) && list.length > 0)
    .map(([channel, list]) => {
      const label = CHANNEL_LABELS[channel] ?? channel
      return (list as unknown[]).length > 1 ? `${label} ×${(list as unknown[]).length}` : label
    })
  return parts.length > 0 ? parts.join(' · ') : 'No destinations'
}
