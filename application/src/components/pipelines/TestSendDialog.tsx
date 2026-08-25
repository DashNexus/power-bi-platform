'use client'

/**
 * Test-send dialog.
 *
 * The old test button posted a fixed string to every group at once, so it proved
 * the webhook worked but told you nothing about the message operators would
 * actually receive. This sends the real rendered template to a chosen subset, and
 * reports the per-destination outcome.
 */
import { useState } from 'react'
import { Send } from 'lucide-react'
import { Badge } from '@/components/ui/Badge'
import { Button } from '@/components/ui/Button'
import { Alert } from '@/components/ui/Feedback'
import { Field, Select } from '@/components/ui/Input'
import { Modal } from '@/components/ui/Modal'
import { NotificationGroupPicker } from './NotificationGroupPicker'
import { CHANNEL_LABELS, type DeliveryDetail, type NotificationGroup } from './notificationTypes'

type TestKind = 'plain' | 'success' | 'failure'

export interface TestSendResult {
  sent: number
  failed: number
  details: DeliveryDetail[]
}

interface TestSendDialogProps {
  open: boolean
  onClose: () => void
  groups: NotificationGroup[]
  pipelines: string[]
  /** Groups pre-selected from the saved config. */
  defaultGroupIds: number[]
  onSend: (payload: {
    group_ids: number[]
    kind: TestKind
    pipeline_name: string | null
  }) => Promise<TestSendResult>
}

export function TestSendDialog({
  open,
  onClose,
  groups,
  pipelines,
  defaultGroupIds,
  onSend,
}: TestSendDialogProps) {
  const [groupIds, setGroupIds] = useState<number[]>(defaultGroupIds)
  const [kind, setKind] = useState<TestKind>('failure')
  const [pipelineName, setPipelineName] = useState<string>('')
  const [sending, setSending] = useState(false)
  const [result, setResult] = useState<TestSendResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function handleSend() {
    setSending(true)
    setError(null)
    setResult(null)
    try {
      setResult(
        await onSend({
          group_ids: groupIds,
          kind,
          pipeline_name: pipelineName || null,
        }),
      )
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Test send failed.')
    } finally {
      setSending(false)
    }
  }

  return (
    <Modal
      open={open}
      onClose={onClose}
      title="Send a test notification"
      description="Delivers a real message to the selected groups so you can confirm routing and formatting."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Close
          </Button>
          <Button onClick={() => void handleSend()} isLoading={sending} disabled={groupIds.length === 0}>
            <Send aria-hidden />
            Send Test
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field
          label="Message to send"
          htmlFor="test-kind"
          hint="Success and failure render your saved template against the most recent matching run."
        >
          <Select id="test-kind" value={kind} onChange={e => setKind(e.target.value as TestKind)}>
            <option value="failure">Your failure message</option>
            <option value="success">Your success message</option>
            <option value="plain">A generic test message</option>
          </Select>
        </Field>

        {kind !== 'plain' && pipelines.length > 0 && (
          <Field
            label="Render as pipeline"
            htmlFor="test-pipeline"
            hint="Picks up that pipeline's override, if it has one."
          >
            <Select
              id="test-pipeline"
              value={pipelineName}
              onChange={e => setPipelineName(e.target.value)}
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
          label="Send to"
          groups={groups}
          selected={groupIds}
          onChange={setGroupIds}
        />

        {error && <Alert tone="danger">{error}</Alert>}

        {result && (
          <Alert tone={result.failed > 0 ? 'warning' : 'success'} title={
            result.failed > 0
              ? `${result.sent} delivered, ${result.failed} failed`
              : `Delivered to ${result.sent} ${result.sent === 1 ? 'destination' : 'destinations'}`
          }>
            {result.details.length > 0 && (
              <ul className="mt-1 space-y-1">
                {result.details.map((d, i) => (
                  <li key={`${d.channel}-${i}`} className="flex flex-wrap items-center gap-2">
                    <Badge tone={d.ok ? 'success' : 'danger'}>
                      {CHANNEL_LABELS[d.channel] ?? d.channel}
                    </Badge>
                    {d.error && <span className="text-xs text-destructive-strong">{d.error}</span>}
                  </li>
                ))}
              </ul>
            )}
          </Alert>
        )}
      </div>
    </Modal>
  )
}
