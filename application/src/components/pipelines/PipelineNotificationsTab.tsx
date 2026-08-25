'use client'

/**
 * Notification configuration for a pipeline connection (admin only).
 *
 * Three sub-views: Settings (defaults, recipients, noise controls, per-pipeline
 * overrides), Condition checks, and Delivery history.
 *
 * Settings are a staged form — edits are held locally and applied with Save, so
 * the tab tracks its own dirty state and warns before losing work. The heavy
 * pieces live in sibling components; this file owns loading, saving, and the
 * shared state between them.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { toast } from 'sonner'
import {
  AlertTriangle,
  Bell,
  BellOff,
  Clock,
  MessageSquare,
  RotateCcw,
  Save,
  Send,
  Users,
  VolumeX,
} from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { Alert, LoadingRows, Spinner } from '@/components/ui/Feedback'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/Card'
import { EmptyState } from '@/components/ui/EmptyState'
import { Field, Select } from '@/components/ui/Input'
import { Tabs, type TabItem } from '@/components/ui/Tabs'
import { Toggle, ToggleRow } from '@/components/ui/Toggle'
import { ConditionChecksSection } from './ConditionChecksSection'
import { DeliveryHistory } from './DeliveryHistory'
import { MessageTemplateEditor } from './MessageTemplateEditor'
import { NotificationGroupPicker } from './NotificationGroupPicker'
import { PipelineOverridesSection } from './PipelineOverridesSection'
import { TestSendDialog, type TestSendResult } from './TestSendDialog'
import {
  POLL_OPTIONS,
  RUN_PLACEHOLDERS,
  THROTTLE_OPTIONS,
  relativeTime,
  type NotifConfig,
  type NotificationGroup,
  type PipelineOverride,
  type PreviewResult,
} from './notificationTypes'

type View = 'settings' | 'conditions' | 'history'

/** Hour options for the quiet-hours selects. */
const HOURS = Array.from({ length: 24 }, (_, h) => ({
  value: h,
  label: `${String(h).padStart(2, '0')}:00`,
}))

/**
 * Timezone list for quiet hours. The browser's own zone is prepended so the
 * common case ("my working day") is one click, with UTC always available.
 */
function timezoneOptions(): string[] {
  const local = Intl.DateTimeFormat().resolvedOptions().timeZone
  const common = [
    'UTC',
    'America/New_York',
    'America/Chicago',
    'America/Denver',
    'America/Los_Angeles',
    'Europe/London',
    'Europe/Berlin',
    'Europe/Madrid',
    'Asia/Kolkata',
    'Asia/Singapore',
    'Asia/Tokyo',
    'Australia/Sydney',
  ]
  return Array.from(new Set([local, ...common].filter(Boolean)))
}

export function PipelineNotificationsTab({
  connectionId,
  token,
}: {
  connectionId: number
  token: string
}) {
  const apiFetch = useMemo(() => createClientFetch(token), [token])

  const [view, setView] = useState<View>('settings')
  const [config, setConfig] = useState<NotifConfig | null>(null)
  // The last saved server state, for dirty comparison and Discard.
  const savedRef = useRef<NotifConfig | null>(null)
  const [groups, setGroups] = useState<NotificationGroup[]>([])
  const [pipelines, setPipelines] = useState<string[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [testOpen, setTestOpen] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setLoadError(null)
    try {
      const [cfg, grps] = await Promise.all([
        apiFetch<NotifConfig>(`/data-pipelines/${connectionId}/notifications`),
        apiFetch<NotificationGroup[]>('/notification-groups').catch(
          () => [] as NotificationGroup[],
        ),
      ])
      const normalised: NotifConfig = { ...cfg, pipeline_overrides: cfg.pipeline_overrides ?? {} }
      setConfig(normalised)
      savedRef.current = normalised
      setGroups(grps)
      // Pipeline names drive the override list and the test dialog; a provider
      // outage should not block the settings form.
      apiFetch<{ pipelines: Array<{ name: string | null }> }>(
        `/data-pipelines/${connectionId}/pipelines`,
      )
        .then(d => setPipelines((d.pipelines ?? []).map(p => p.name ?? '').filter(Boolean)))
        .catch(() => setPipelines([]))
    } catch (err) {
      setLoadError(err instanceof Error ? err.message : 'Failed to load notification settings.')
    } finally {
      setLoading(false)
    }
  }, [apiFetch, connectionId])

  useEffect(() => {
    void load()
  }, [load])

  const isDirty = useMemo(
    () => !!config && JSON.stringify(config) !== JSON.stringify(savedRef.current),
    [config],
  )

  // Guard a full page unload. In-app navigation is guarded by the banner + the
  // Save button staying visible, since the App Router has no navigation block.
  useEffect(() => {
    if (!isDirty) return
    function warn(e: BeforeUnloadEvent) {
      e.preventDefault()
    }
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [isDirty])

  function update(patch: Partial<NotifConfig>) {
    setConfig(prev => (prev ? { ...prev, ...patch } : prev))
  }

  function setOverride(name: string, override: PipelineOverride) {
    setConfig(prev => {
      if (!prev) return prev
      const next = { ...prev.pipeline_overrides }
      if (Object.keys(override).length === 0) delete next[name]
      else next[name] = override
      return { ...prev, pipeline_overrides: next }
    })
  }

  async function handleSave() {
    if (!config) return
    setSaving(true)
    try {
      const saved = await apiFetch<NotifConfig>(
        `/data-pipelines/${connectionId}/notifications`,
        { method: 'PUT', body: JSON.stringify(config) },
      )
      const normalised: NotifConfig = {
        ...saved,
        pipeline_overrides: saved.pipeline_overrides ?? {},
      }
      setConfig(normalised)
      savedRef.current = normalised
      toast.success('Notification settings saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save settings.')
    } finally {
      setSaving(false)
    }
  }

  function handleDiscard() {
    if (savedRef.current) setConfig(savedRef.current)
  }

  const preview = useCallback(
    async (
      kind: 'success' | 'failure',
      template: string,
      pipelineName?: string,
    ): Promise<PreviewResult> =>
      apiFetch<PreviewResult>(`/data-pipelines/${connectionId}/notifications/preview`, {
        method: 'POST',
        body: JSON.stringify({ kind, template, pipeline_name: pipelineName ?? null }),
      }),
    [apiFetch, connectionId],
  )

  const sendTest = useCallback(
    async (payload: {
      group_ids: number[]
      kind: 'plain' | 'success' | 'failure'
      pipeline_name: string | null
    }): Promise<TestSendResult> =>
      apiFetch<TestSendResult>(`/data-pipelines/${connectionId}/notifications/test`, {
        method: 'POST',
        body: JSON.stringify(payload),
      }),
    [apiFetch, connectionId],
  )

  if (loading) {
    return (
      <div className="space-y-4">
        <LoadingRows rows={5} />
      </div>
    )
  }

  if (loadError || !config) {
    return (
      <Alert tone="danger" title="Notification settings unavailable">
        {loadError ?? 'The configuration could not be loaded.'}
      </Alert>
    )
  }

  const allGroupIds = Array.from(
    new Set([...config.success_group_ids, ...config.failure_group_ids]),
  )
  const quietHoursOn = config.quiet_hours_start !== null && config.quiet_hours_end !== null
  // "Armed" means the poller would actually deliver something.
  const armed =
    config.enabled &&
    ((config.notify_on_success && config.success_group_ids.length > 0) ||
      (config.notify_on_failure && config.failure_group_ids.length > 0))

  const tabs: ReadonlyArray<TabItem<View>> = [
    { id: 'settings', label: 'Settings', badge: isDirty ? <Badge tone="warning">Unsaved</Badge> : undefined },
    { id: 'conditions', label: 'Condition checks' },
    { id: 'history', label: 'Delivery history' },
  ]

  return (
    <div className="space-y-5">
      {/* Status header — the poller's actual state, which was invisible before. */}
      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-4 py-4">
          <div className="flex min-w-0 items-start gap-3">
            <span
              className={
                armed
                  ? 'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-success-subtle text-success-strong'
                  : 'flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-muted text-muted-foreground'
              }
            >
              {armed ? <Bell className="h-4 w-4" aria-hidden /> : <BellOff className="h-4 w-4" aria-hidden />}
            </span>
            <div className="min-w-0">
              <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-foreground">
                {config.enabled ? 'Run notifications are on' : 'Run notifications are off'}
                {config.enabled && !armed && <Badge tone="warning">Nothing would be sent</Badge>}
                {quietHoursOn && (
                  <Badge tone="neutral">
                    Quiet {String(config.quiet_hours_start).padStart(2, '0')}:00–
                    {String(config.quiet_hours_end).padStart(2, '0')}:00
                  </Badge>
                )}
              </p>
              <p className="mt-0.5 text-xs text-muted-foreground">
                {config.enabled ? (
                  <>
                    Last checked {relativeTime(config.last_polled_at)}
                    {config.next_poll_due_at && <> · next check {relativeTime(config.next_poll_due_at)}</>}
                  </>
                ) : (
                  'Enable to start polling this connection for finished runs.'
                )}
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={() => setTestOpen(true)}
              disabled={groups.length === 0}
              title={groups.length === 0 ? 'Create a notification group first' : 'Send a test notification'}
            >
              <Send aria-hidden />
              Send Test
            </Button>
            <Toggle
              checked={config.enabled}
              onCheckedChange={checked => update({ enabled: checked })}
              ariaLabel="Enable run notifications for this connection"
            />
          </div>
        </CardContent>
      </Card>

      {config.enabled && !armed && (
        <Alert tone="warning" title="No alert would reach anyone">
          Notifications are on, but every enabled outcome is missing a notification group. Pick a
          group under <strong>Recipients</strong> below.
        </Alert>
      )}

      <Tabs tabs={tabs} active={view} onChange={setView} aria-label="Notification settings" />

      {view === 'settings' && (
        <div className="space-y-5">
          {isDirty && (
            <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-warning-subtle bg-warning-subtle px-3.5 py-2.5">
              <span className="flex items-center gap-2 text-sm text-foreground">
                <AlertTriangle className="h-4 w-4 shrink-0 text-warning-strong" aria-hidden />
                You have unsaved changes.
              </span>
              <span className="flex items-center gap-2">
                <Button variant="ghost" size="sm" onClick={handleDiscard} disabled={saving}>
                  <RotateCcw aria-hidden />
                  Discard
                </Button>
                <Button size="sm" onClick={() => void handleSave()} isLoading={saving}>
                  <Save aria-hidden />
                  Save Changes
                </Button>
              </span>
            </div>
          )}

          {/* When to notify + the message templates. */}
          <Card>
            <CardHeader>
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-primary-subtle text-info-strong">
                  <MessageSquare className="h-4 w-4" aria-hidden />
                </span>
                <div className="min-w-0">
                  <CardTitle>When to notify</CardTitle>
                  <CardDescription>
                    Connection-wide defaults. Individual pipelines can override them below.
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="grid gap-3 sm:grid-cols-2">
                <ToggleRow
                  label="Notify on success"
                  hint="Usually off — successful runs are the normal case."
                  checked={config.notify_on_success}
                  onCheckedChange={checked => update({ notify_on_success: checked })}
                />
                <ToggleRow
                  label="Notify on failure"
                  hint="Recommended."
                  checked={config.notify_on_failure}
                  onCheckedChange={checked => update({ notify_on_failure: checked })}
                />
              </div>

              <div className="grid gap-5 sm:grid-cols-2">
                <MessageTemplateEditor
                  label="Default success message"
                  value={config.success_message}
                  onChange={v => update({ success_message: v })}
                  placeholders={RUN_PLACEHOLDERS}
                  onPreview={template => preview('success', template)}
                />
                <MessageTemplateEditor
                  label="Default failure message"
                  value={config.failure_message}
                  onChange={v => update({ failure_message: v })}
                  placeholders={RUN_PLACEHOLDERS}
                  onPreview={template => preview('failure', template)}
                />
              </div>

              <Field
                label="Check for finished runs"
                htmlFor="poll-freq"
                hint="How often the poller asks the provider for new runs. Alerts can only be as timely as this."
              >
                <Select
                  id="poll-freq"
                  value={config.poll_frequency_minutes}
                  onChange={e => update({ poll_frequency_minutes: Number(e.target.value) })}
                  className="sm:w-72"
                >
                  {POLL_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </CardContent>
          </Card>

          {/* Recipients. */}
          <Card>
            <CardHeader>
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-assistant-subtle text-assistant">
                  <Users className="h-4 w-4" aria-hidden />
                </span>
                <div className="min-w-0">
                  <CardTitle>Recipients</CardTitle>
                  <CardDescription>
                    Success and failure route independently, so noisy successes need not reach the
                    on-call group.
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              <div className="grid gap-6 sm:grid-cols-2">
                <NotificationGroupPicker
                  label="On success → send to"
                  groups={groups}
                  selected={config.success_group_ids}
                  onChange={v => update({ success_group_ids: v })}
                  warnWhenEmpty={config.enabled && config.notify_on_success}
                />
                <NotificationGroupPicker
                  label="On failure → send to"
                  groups={groups}
                  selected={config.failure_group_ids}
                  onChange={v => update({ failure_group_ids: v })}
                  warnWhenEmpty={config.enabled && config.notify_on_failure}
                />
              </div>
            </CardContent>
          </Card>

          {/* Noise controls. */}
          <Card>
            <CardHeader>
              <div className="flex items-start gap-3">
                <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-warning-subtle text-warning-strong">
                  <VolumeX className="h-4 w-4" aria-hidden />
                </span>
                <div className="min-w-0">
                  <CardTitle>Noise controls</CardTitle>
                  <CardDescription>
                    Keep a flapping pipeline from burying a channel — a muted channel alerts nobody.
                  </CardDescription>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              <Field
                label="Rate limit per pipeline"
                htmlFor="throttle"
                hint="Applied per pipeline and per outcome, so a failure never suppresses a success."
              >
                <Select
                  id="throttle"
                  value={config.min_interval_minutes}
                  onChange={e => update({ min_interval_minutes: Number(e.target.value) })}
                  className="sm:w-72"
                >
                  {THROTTLE_OPTIONS.map(o => (
                    <option key={o.value} value={o.value}>
                      {o.label}
                    </option>
                  ))}
                </Select>
              </Field>

              <div className="space-y-3 rounded-lg border border-border p-3">
                <div className="flex items-center justify-between gap-3">
                  <div className="min-w-0">
                    <p className="flex items-center gap-1.5 text-sm text-foreground">
                      <Clock className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                      Quiet hours
                    </p>
                    <p className="mt-0.5 text-xs text-muted-foreground">
                      Hold alerts during a recurring window. Failures still go out unless you
                      include them.
                    </p>
                  </div>
                  <Toggle
                    checked={quietHoursOn}
                    ariaLabel="Enable quiet hours"
                    onCheckedChange={checked =>
                      update(
                        checked
                          ? { quiet_hours_start: 22, quiet_hours_end: 6 }
                          : { quiet_hours_start: null, quiet_hours_end: null },
                      )
                    }
                  />
                </div>

                {quietHoursOn && (
                  <>
                    <div className="grid gap-3 sm:grid-cols-3">
                      <Field label="From" htmlFor="qh-start">
                        <Select
                          id="qh-start"
                          value={config.quiet_hours_start ?? 22}
                          onChange={e => update({ quiet_hours_start: Number(e.target.value) })}
                        >
                          {HOURS.map(h => (
                            <option key={h.value} value={h.value}>
                              {h.label}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label="Until" htmlFor="qh-end">
                        <Select
                          id="qh-end"
                          value={config.quiet_hours_end ?? 6}
                          onChange={e => update({ quiet_hours_end: Number(e.target.value) })}
                        >
                          {HOURS.map(h => (
                            <option key={h.value} value={h.value}>
                              {h.label}
                            </option>
                          ))}
                        </Select>
                      </Field>
                      <Field label="Timezone" htmlFor="qh-tz">
                        <Select
                          id="qh-tz"
                          value={config.quiet_hours_tz}
                          onChange={e => update({ quiet_hours_tz: e.target.value })}
                        >
                          {timezoneOptions().map(tz => (
                            <option key={tz} value={tz}>
                              {tz}
                            </option>
                          ))}
                        </Select>
                      </Field>
                    </div>
                    {config.quiet_hours_start === config.quiet_hours_end && (
                      <Alert tone="warning">
                        Start and end are the same, which is treated as no window at all. Pick
                        different hours.
                      </Alert>
                    )}
                    <ToggleRow
                      label="Silence failures too"
                      hint="Off is safer: an outage usually outranks the on-call schedule."
                      checked={config.quiet_hours_include_failures}
                      onCheckedChange={checked =>
                        update({ quiet_hours_include_failures: checked })
                      }
                    />
                  </>
                )}
              </div>
            </CardContent>
          </Card>

          {pipelines.length > 0 ? (
            <PipelineOverridesSection
              pipelines={pipelines}
              config={config}
              onSetOverride={setOverride}
              onPreview={(kind, template, pipeline) => preview(kind, template, pipeline)}
            />
          ) : (
            <EmptyState
              title="No pipelines to override"
              description="Per-pipeline overrides appear once this connection reports its pipeline definitions. Check the Pipelines tab if you expected some."
            />
          )}

          {/* Persistent save row so Save is reachable without scrolling back up. */}
          <div className="flex items-center gap-2 border-t border-border pt-4">
            <Button onClick={() => void handleSave()} isLoading={saving} disabled={!isDirty}>
              <Save aria-hidden />
              Save Settings
            </Button>
            {isDirty ? (
              <Button variant="ghost" onClick={handleDiscard} disabled={saving}>
                Discard changes
              </Button>
            ) : (
              <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                {saving ? <Spinner /> : null}
                All changes saved
              </span>
            )}
          </div>
        </div>
      )}

      {view === 'conditions' && (
        <ConditionChecksSection
          connectionId={connectionId}
          apiFetch={apiFetch}
          groups={groups}
          pipelines={pipelines}
        />
      )}

      {view === 'history' && <DeliveryHistory connectionId={connectionId} apiFetch={apiFetch} />}

      <TestSendDialog
        key={testOpen ? 'open' : 'closed'}
        open={testOpen}
        onClose={() => setTestOpen(false)}
        groups={groups}
        pipelines={pipelines}
        defaultGroupIds={allGroupIds}
        onSend={sendTest}
      />
    </div>
  )
}
