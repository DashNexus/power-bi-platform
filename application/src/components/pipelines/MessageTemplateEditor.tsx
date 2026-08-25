'use client'

/**
 * Message template editor with click-to-insert placeholders and live preview.
 *
 * Previously a template could only be verified by waiting for a real pipeline
 * run: the editor showed the raw string and the "Send test" button ignored it
 * entirely. Preview renders server-side against the newest matching real run, so
 * placeholders that a given provider never populates are obvious immediately.
 */
import { useCallback, useEffect, useRef, useState } from 'react'
import { Eye, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { Alert } from '@/components/ui/Feedback'
import { Badge } from '@/components/ui/Badge'
import { Label, Textarea } from '@/components/ui/Input'
import type { PreviewResult } from './notificationTypes'

interface MessageTemplateEditorProps {
  label: string
  value: string
  onChange: (value: string) => void
  placeholders: readonly string[]
  /** Omit to disable the preview button (per-pipeline override rows). */
  onPreview?: (template: string) => Promise<PreviewResult>
  rows?: number
  hint?: string
  placeholder?: string
}

export function MessageTemplateEditor({
  label,
  value,
  onChange,
  placeholders,
  onPreview,
  rows = 3,
  hint,
  placeholder,
}: MessageTemplateEditorProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null)
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // Any edit invalidates the rendered preview; keeping it would show a result
  // that no longer matches the text on screen.
  useEffect(() => {
    setPreview(null)
  }, [value])

  /** Insert `{name}` at the caret rather than appending at the end. */
  function insert(name: string) {
    const el = textareaRef.current
    const token = `{${name}}`
    if (!el) {
      onChange(value + token)
      return
    }
    const start = el.selectionStart ?? value.length
    const end = el.selectionEnd ?? value.length
    onChange(value.slice(0, start) + token + value.slice(end))
    // Restore focus and place the caret after the inserted token.
    requestAnimationFrame(() => {
      el.focus()
      el.setSelectionRange(start + token.length, start + token.length)
    })
  }

  const runPreview = useCallback(async () => {
    if (!onPreview) return
    setLoading(true)
    setError(null)
    try {
      setPreview(await onPreview(value))
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Preview failed.')
    } finally {
      setLoading(false)
    }
  }, [onPreview, value])

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between gap-2">
        <Label>{label}</Label>
        {onPreview && (
          <Button variant="ghost" size="sm" onClick={() => void runPreview()} disabled={loading}>
            {loading ? <Loader2 className="animate-spin" aria-hidden /> : <Eye aria-hidden />}
            Preview
          </Button>
        )}
      </div>

      <Textarea
        ref={textareaRef}
        value={value}
        onChange={e => onChange(e.target.value)}
        rows={rows}
        placeholder={placeholder}
        className="font-mono text-xs"
      />

      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}

      <div className="flex flex-wrap gap-1">
        {placeholders.map(p => (
          <button
            key={p}
            type="button"
            onClick={() => insert(p)}
            title={`Insert {${p}}`}
            className="rounded bg-muted px-1.5 py-0.5 font-mono text-[11px] text-muted-foreground transition-colors hover:bg-primary-subtle hover:text-info-strong"
          >
            {`{${p}}`}
          </button>
        ))}
      </div>

      {error && <Alert tone="danger">{error}</Alert>}

      {preview && (
        <div className="space-y-1.5 rounded-lg border border-border bg-muted/50 p-3">
          <div className="flex items-center justify-between gap-2">
            <p className="text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Preview
            </p>
            <Badge tone={preview.used_sample ? 'warning' : 'info'}>
              {preview.used_sample ? 'Sample data' : 'Latest real run'}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">{preview.subject}</p>
          <p className="whitespace-pre-wrap break-words text-sm text-foreground">
            {preview.message || <span className="italic text-muted-foreground">(empty message)</span>}
          </p>
          {preview.used_sample && (
            <p className="text-xs text-muted-foreground">
              No matching run was found in the last 14 days, so placeholder values are illustrative.
            </p>
          )}
        </div>
      )}
    </div>
  )
}
