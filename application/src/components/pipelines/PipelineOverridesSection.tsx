'use client'

/**
 * Per-pipeline overrides of the connection's notification defaults.
 *
 * A connection can expose hundreds of pipelines (Azure Data Factory routinely
 * does), so the list is searchable and can be narrowed to just the pipelines
 * that already carry an override — the previous version rendered every pipeline
 * in one unfiltered scroll box.
 */
import { useMemo, useState } from 'react'
import { ChevronDown, ChevronRight, RotateCcw, Search, SlidersHorizontal } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Card, CardContent, CardHeader, CardDescription, CardTitle } from '@/components/ui/Card'
import { Input, Label, Select } from '@/components/ui/Input'
import { MessageTemplateEditor } from './MessageTemplateEditor'
import {
  RUN_PLACEHOLDERS,
  type NotifConfig,
  type PipelineOverride,
  type PreviewResult,
} from './notificationTypes'

/** Inherit / On / Off, mapped to boolean | undefined. */
function TriState({
  label,
  value,
  onChange,
  inheritedValue,
}: {
  label: string
  value: boolean | undefined
  onChange: (v: boolean | undefined) => void
  inheritedValue: boolean
}) {
  const str = value === undefined ? 'inherit' : value ? 'on' : 'off'
  return (
    <div className="space-y-1">
      <Label className="text-xs">{label}</Label>
      <Select
        value={str}
        onChange={e =>
          onChange(e.target.value === 'inherit' ? undefined : e.target.value === 'on')
        }
        className="text-xs"
      >
        <option value="inherit">Inherit ({inheritedValue ? 'on' : 'off'})</option>
        <option value="on">On</option>
        <option value="off">Off</option>
      </Select>
    </div>
  )
}

interface OverrideRowProps {
  name: string
  override: PipelineOverride
  defaults: Pick<NotifConfig, 'notify_on_success' | 'notify_on_failure'>
  onChange: (o: PipelineOverride) => void
  onPreview: (kind: 'success' | 'failure', template: string, pipeline: string) => Promise<PreviewResult>
}

function OverrideRow({ name, override, defaults, onChange, onPreview }: OverrideRowProps) {
  const [open, setOpen] = useState(false)
  const hasOverride = Object.keys(override).length > 0

  function patch(p: Partial<PipelineOverride>) {
    const next: PipelineOverride = { ...override, ...p }
    // A field set back to "inherit" (undefined) or blank must be dropped, not
    // stored — an empty string would otherwise override with an empty message.
    for (const k of Object.keys(next) as (keyof PipelineOverride)[]) {
      if (next[k] === undefined || next[k] === '') delete next[k]
    }
    onChange(next)
  }

  const effSuccess = override.notify_on_success ?? defaults.notify_on_success
  const effFailure = override.notify_on_failure ?? defaults.notify_on_failure

  return (
    <div className="border-b border-border last:border-0">
      <div className="flex items-center gap-2 pr-2">
        <button
          type="button"
          onClick={() => setOpen(o => !o)}
          aria-expanded={open}
          className="flex min-w-0 flex-1 items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-accent"
        >
          {open ? (
            <ChevronDown className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          ) : (
            <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" aria-hidden />
          )}
          <span className="min-w-0 flex-1 truncate text-sm text-foreground">{name}</span>
          <Badge tone={effSuccess ? 'success' : 'neutral'}>
            Success {effSuccess ? 'on' : 'off'}
          </Badge>
          <Badge tone={effFailure ? 'danger' : 'neutral'}>
            Failure {effFailure ? 'on' : 'off'}
          </Badge>
          {hasOverride && <Badge tone="primary">Override</Badge>}
        </button>
        {hasOverride && (
          <Button
            variant="ghost"
            size="icon-sm"
            title={`Reset ${name} to the connection defaults`}
            aria-label={`Reset ${name} to the connection defaults`}
            onClick={() => onChange({})}
          >
            <RotateCcw aria-hidden />
          </Button>
        )}
      </div>

      {open && (
        <div className="space-y-3 bg-muted/40 px-9 py-3">
          <div className="grid gap-3 sm:grid-cols-2">
            <TriState
              label="Notify on success"
              value={override.notify_on_success}
              onChange={v => patch({ notify_on_success: v })}
              inheritedValue={defaults.notify_on_success}
            />
            <TriState
              label="Notify on failure"
              value={override.notify_on_failure}
              onChange={v => patch({ notify_on_failure: v })}
              inheritedValue={defaults.notify_on_failure}
            />
          </div>
          <MessageTemplateEditor
            label="Custom success message"
            hint="Leave blank to inherit the connection default."
            value={override.success_message ?? ''}
            onChange={v => patch({ success_message: v })}
            placeholders={RUN_PLACEHOLDERS}
            rows={2}
            onPreview={
              override.success_message
                ? template => onPreview('success', template, name)
                : undefined
            }
          />
          <MessageTemplateEditor
            label="Custom failure message"
            hint="Leave blank to inherit the connection default."
            value={override.failure_message ?? ''}
            onChange={v => patch({ failure_message: v })}
            placeholders={RUN_PLACEHOLDERS}
            rows={2}
            onPreview={
              override.failure_message
                ? template => onPreview('failure', template, name)
                : undefined
            }
          />
        </div>
      )}
    </div>
  )
}

interface PipelineOverridesSectionProps {
  pipelines: string[]
  config: NotifConfig
  onSetOverride: (name: string, override: PipelineOverride) => void
  onPreview: (kind: 'success' | 'failure', template: string, pipeline: string) => Promise<PreviewResult>
}

export function PipelineOverridesSection({
  pipelines,
  config,
  onSetOverride,
  onPreview,
}: PipelineOverridesSectionProps) {
  const [search, setSearch] = useState('')
  const [onlyOverridden, setOnlyOverridden] = useState(false)

  const overrideCount = useMemo(
    () => Object.values(config.pipeline_overrides).filter(o => Object.keys(o).length > 0).length,
    [config.pipeline_overrides],
  )

  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return pipelines.filter(name => {
      if (onlyOverridden && Object.keys(config.pipeline_overrides[name] ?? {}).length === 0) {
        return false
      }
      return !q || name.toLowerCase().includes(q)
    })
  }, [pipelines, search, onlyOverridden, config.pipeline_overrides])

  return (
    <Card>
      <CardHeader>
        <div className="flex items-start gap-3">
          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg bg-warning-subtle text-warning-strong">
            <SlidersHorizontal className="h-4 w-4" aria-hidden />
          </span>
          <div className="min-w-0">
            <CardTitle>Per-pipeline overrides</CardTitle>
            <CardDescription>
              Every pipeline inherits the defaults above. Override a single pipeline&apos;s
              on/off switches or its message.
              {overrideCount > 0 && ` ${overrideCount} currently overridden.`}
            </CardDescription>
          </div>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-48 flex-1">
            <Search
              className="pointer-events-none absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground"
              aria-hidden
            />
            <Input
              type="search"
              value={search}
              onChange={e => setSearch(e.target.value)}
              placeholder={`Search ${pipelines.length} pipelines…`}
              aria-label="Search pipelines"
              className="pl-8 text-xs"
            />
          </div>
          <Button
            variant={onlyOverridden ? 'primary' : 'outline'}
            size="sm"
            onClick={() => setOnlyOverridden(v => !v)}
            disabled={overrideCount === 0}
            title={
              overrideCount === 0
                ? 'No pipeline has an override yet'
                : 'Show only pipelines with an override'
            }
          >
            Overridden only
          </Button>
        </div>

        {visible.length === 0 ? (
          <p className="rounded-lg border border-dashed border-border px-4 py-6 text-center text-xs text-muted-foreground">
            {onlyOverridden
              ? 'No pipeline has an override yet.'
              : 'No pipeline matches that search.'}
          </p>
        ) : (
          <div className="max-h-96 overflow-y-auto rounded-lg border border-border">
            {visible.map(name => (
              <OverrideRow
                key={name}
                name={name}
                override={config.pipeline_overrides[name] ?? {}}
                defaults={config}
                onChange={o => onSetOverride(name, o)}
                onPreview={onPreview}
              />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  )
}
