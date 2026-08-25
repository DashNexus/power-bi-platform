/**
 * Tests for the shared notification formatting helpers.
 *
 * These drive user-facing summaries on the settings and history views, so a
 * regression here silently mislabels thresholds and check cadences.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'
import {
  conditionSummary,
  describeChannels,
  formatDuration,
  relativeTime,
  splitThreshold,
  type NotificationCondition,
} from '@/components/pipelines/notificationTypes'

function condition(overrides: Partial<NotificationCondition> = {}): NotificationCondition {
  return {
    id: 1,
    pipeline_connection_id: 1,
    name: 'Check',
    condition_type: 'pipeline_idle',
    enabled: true,
    threshold_minutes: 360,
    check_frequency_minutes: 60,
    pipeline_name: null,
    warehouse_connection_id: null,
    schema_name: null,
    table_name: null,
    timestamp_column: null,
    group_ids: [],
    message_template: '',
    notify_on_recovery: true,
    is_triggered: false,
    last_checked_at: null,
    last_observed_at: null,
    last_error: null,
    ...overrides,
  }
}

describe('formatDuration', () => {
  it('renders sub-hour values in minutes', () => {
    expect(formatDuration(45)).toBe('45m')
  })

  it('renders whole hours without a minute part', () => {
    expect(formatDuration(120)).toBe('2h')
  })

  it('renders mixed hours and minutes', () => {
    expect(formatDuration(90)).toBe('1h 30m')
  })

  it('collapses whole days', () => {
    expect(formatDuration(2880)).toBe('2d')
  })

  it('keeps a non-whole day in hours', () => {
    expect(formatDuration(1500)).toBe('25h')
  })
})

describe('splitThreshold', () => {
  it('round-trips a whole number of days', () => {
    expect(splitThreshold(2880)).toEqual({ value: 2, unit: 'days' })
  })

  it('round-trips a whole number of hours', () => {
    expect(splitThreshold(180)).toEqual({ value: 3, unit: 'hours' })
  })

  it('falls back to minutes when the value divides evenly into neither', () => {
    expect(splitThreshold(95)).toEqual({ value: 95, unit: 'minutes' })
  })

  it('reconstructs the original minute count', () => {
    for (const minutes of [5, 45, 60, 90, 1440, 2880, 4321]) {
      const { value, unit } = splitThreshold(minutes)
      const factor = unit === 'days' ? 1440 : unit === 'hours' ? 60 : 1
      expect(value * factor).toBe(minutes)
    }
  })
})

describe('relativeTime', () => {
  afterEach(() => {
    vi.useRealTimers()
  })

  it('reports never for a missing timestamp', () => {
    expect(relativeTime(null)).toBe('never')
  })

  it('reports unknown for an unparseable timestamp', () => {
    expect(relativeTime('not-a-date')).toBe('unknown')
  })

  it('describes a past timestamp as elapsed', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-30T12:00:00Z'))

    expect(relativeTime('2026-07-30T11:30:00Z')).toBe('30m ago')
  })

  it('describes a future timestamp as upcoming', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-30T12:00:00Z'))

    expect(relativeTime('2026-07-30T14:00:00Z')).toBe('in 2h')
  })

  it('collapses a sub-minute difference to just now', () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date('2026-07-30T12:00:00Z'))

    expect(relativeTime('2026-07-30T12:00:20Z')).toBe('just now')
  })
})

describe('conditionSummary', () => {
  it('describes an any-pipeline idle check', () => {
    const summary = conditionSummary(condition())

    expect(summary).toBe('No runs in 6h — checks every hour')
  })

  it('names the pipeline when the check is scoped to one', () => {
    const summary = conditionSummary(condition({ pipeline_name: 'LoadOrders' }))

    expect(summary).toContain('"LoadOrders" — no runs')
  })

  it('describes a freshness check by its table path', () => {
    const summary = conditionSummary(
      condition({
        condition_type: 'data_freshness',
        schema_name: 'marts',
        table_name: 'fct_orders',
        timestamp_column: 'updated_at',
        threshold_minutes: 1440,
      }),
    )

    expect(summary).toContain('marts.fct_orders.updated_at older than 1d')
  })

  it('defaults a blank schema to marts', () => {
    const summary = conditionSummary(
      condition({
        condition_type: 'data_freshness',
        schema_name: null,
        table_name: 'fct_orders',
        timestamp_column: 'updated_at',
      }),
    )

    expect(summary).toContain('marts.fct_orders')
  })

  it('falls back to a formatted cadence for a non-preset frequency', () => {
    const summary = conditionSummary(condition({ check_frequency_minutes: 25 }))

    expect(summary).toContain('checks every 25m')
  })
})

describe('describeChannels', () => {
  it('reports when a group has no destinations', () => {
    expect(describeChannels({ id: 1, name: 'Empty', channels: {} })).toBe('No destinations')
  })

  it('reports when the channels map is absent entirely', () => {
    expect(describeChannels({ id: 1, name: 'Empty' })).toBe('No destinations')
  })

  it('labels a single destination without a count', () => {
    const summary = describeChannels({ id: 1, name: 'Ops', channels: { slack: ['url'] } })

    expect(summary).toBe('Slack')
  })

  it('appends a count when a channel has several destinations', () => {
    const summary = describeChannels({
      id: 1,
      name: 'Ops',
      channels: { slack: ['a', 'b'], email: [1, 2, 3] },
    })

    expect(summary).toBe('Slack ×2 · Email ×3')
  })

  it('omits channels that are present but empty', () => {
    const summary = describeChannels({
      id: 1,
      name: 'Ops',
      channels: { slack: ['a'], teams: [], sms: [] },
    })

    expect(summary).toBe('Slack')
  })
})
