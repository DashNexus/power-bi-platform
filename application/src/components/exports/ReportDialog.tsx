'use client'

/**
 * Create or edit a SQL report.
 *
 * A report runs a read-only query against a chosen source — a named warehouse
 * connection, or the operations database this application runs on — and
 * delivers the result. Scheduling is optional: a report with no cron expression
 * runs only when someone presses Run.
 *
 * The same dialog serves both create and edit, because a report is defined by
 * one set of fields and two forms would drift.
 */
import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { AlertTriangle, FlaskConical } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { ReportPreviewPanel } from '@/components/exports/ReportPreviewPanel'
import type { Report, ReportPreview, ReportSourceKind } from '@/components/exports/types'
import { Alert, Button, Field, Input, Modal, Select, Textarea, ToggleRow } from '@/components/ui'

interface WarehouseConnection {
  id: number
  name: string
  db_type: string
}

interface ReportDialogProps {
  /** The report being edited, or null to create a new one. */
  report?: Report | null
  /** True when the signed-in user may target the operations database. */
  canUseOperations?: boolean
  onClose: () => void
  onSaved: () => void
}

const CRON_PRESETS: ReadonlyArray<{ label: string; value: string }> = [
  { label: 'Every hour', value: '0 * * * *' },
  { label: 'Daily at 06:00', value: '0 6 * * *' },
  { label: 'Weekdays at 08:00', value: '0 8 * * 1-5' },
  { label: 'Mondays at 06:00', value: '0 6 * * 1' },
  { label: 'First of the month', value: '0 6 1 * *' },
]

export function ReportDialog({
  report = null,
  canUseOperations = false,
  onClose,
  onSaved,
}: ReportDialogProps) {
  const { data: session } = useSession()
  const isEdit = report !== null

  const [name, setName] = useState(report?.name ?? '')
  const [sqlQuery, setSqlQuery] = useState(report?.sql_query ?? '')
  const [sourceKind, setSourceKind] = useState<ReportSourceKind>(report?.source_kind ?? 'warehouse')
  const [warehouseConnectionId, setWarehouseConnectionId] = useState<number | ''>(
    report?.warehouse_connection_id ?? '',
  )
  const [format, setFormat] = useState(report?.format ?? 'csv')
  const [isScheduled, setIsScheduled] = useState(Boolean(report?.cron_expression))
  const [cron, setCron] = useState(report?.cron_expression ?? '0 6 * * 1')
  const [isActive, setIsActive] = useState(report?.is_active ?? true)
  const [deliveryMethod, setDeliveryMethod] = useState(report?.delivery_method ?? 'download')

  const config = report?.delivery_config ?? {}
  const [sftpHost, setSftpHost] = useState((config.host as string) ?? '')
  const [sftpPort, setSftpPort] = useState(String((config.port as number) ?? 22))
  const [sftpUsername, setSftpUsername] = useState((config.username as string) ?? '')
  const [sftpPassword, setSftpPassword] = useState('')
  const [sftpRemotePath, setSftpRemotePath] = useState((config.remote_path as string) ?? '/reports')

  const [connections, setConnections] = useState<WarehouseConnection[]>([])
  const [connectionsLoaded, setConnectionsLoaded] = useState(false)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [testing, setTesting] = useState(false)
  const [preview, setPreview] = useState<ReportPreview | null>(null)
  const [testError, setTestError] = useState<string | null>(null)

  useEffect(() => {
    const token = session?.user?.access_token
    if (!token) return
    const apiFetch = createClientFetch(token)
    apiFetch<WarehouseConnection[]>('/warehouses')
      .then(data => {
        setConnections(data)
        // Only default when creating: an edit must not silently repoint an
        // existing report at a different database.
        if (!isEdit && data.length > 0) {
          setWarehouseConnectionId(current => (current === '' ? data[0].id : current))
        }
      })
      .catch(() => setConnections([]))
      .finally(() => setConnectionsLoaded(true))
  }, [session, isEdit])

  function buildDeliveryConfig(): Record<string, unknown> | null {
    // No email branch: the option is disabled here and refused by the API, so
    // the recipients field would be plumbing for a path nothing can reach.
    if (deliveryMethod === 'sftp') {
      return {
        host: sftpHost,
        port: parseInt(sftpPort, 10) || 22,
        username: sftpUsername,
        // An unchanged password field means "keep what is stored"; sending an
        // empty string would wipe it.
        ...(sftpPassword ? { password: sftpPassword } : {}),
        remote_path: sftpRemotePath || '/reports',
      }
    }
    return null
  }

  /**
   * The report definition, as both Save and Test send it. Shared on purpose:
   * a Test that passed while Save sent something slightly different would be
   * worse than no Test at all.
   */
  function buildBody(): Record<string, unknown> {
    return {
      name: name.trim() || 'Untitled report',
      format,
      cron_expression: isScheduled ? cron.trim() : null,
      sql_query: sqlQuery.trim(),
      source_kind: sourceKind,
      warehouse_connection_id: sourceKind === 'warehouse' ? warehouseConnectionId || null : null,
      delivery_method: deliveryMethod,
      delivery_config: buildDeliveryConfig(),
      query_params: {},
      is_active: isActive,
    }
  }

  async function handleTest() {
    setTesting(true)
    setTestError(null)
    setPreview(null)
    try {
      const apiFetch = createClientFetch(session?.user?.access_token)
      setPreview(
        await apiFetch<ReportPreview>('/exports/reports/test', {
          method: 'POST',
          body: JSON.stringify(buildBody()),
        }),
      )
    } catch (err) {
      setTestError(err instanceof Error ? err.message : 'The test could not be run.')
    } finally {
      setTesting(false)
    }
  }

  const needsConnection = sourceKind === 'warehouse'
  // Testing needs less than saving does: a query and somewhere to run it. Name
  // and delivery are irrelevant to whether the SQL works.
  const canTest = sqlQuery.trim().length > 0 && (!needsConnection || warehouseConnectionId !== '')
  const isValid =
    name.trim().length > 0 &&
    sqlQuery.trim().length > 0 &&
    (!needsConnection || warehouseConnectionId !== '') &&
    (!isScheduled || cron.trim().length > 0)

  async function handleSave() {
    if (!isValid) return
    setSaving(true)
    setError(null)
    try {
      const apiFetch = createClientFetch(session?.user?.access_token)
      await apiFetch<unknown>(isEdit ? `/exports/reports/${report.id}` : '/exports/reports', {
        method: isEdit ? 'PUT' : 'POST',
        body: JSON.stringify({ ...buildBody(), name: name.trim() }),
      })
      onSaved()
      onClose()
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Could not save the report.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      size="lg"
      title={isEdit ? 'Edit report' : 'New SQL report'}
      description="Runs a read-only query and delivers the result. Scheduling is optional."
      footer={
        <>
          <Button variant="outline" onClick={onClose}>
            Cancel
          </Button>
          <Button
            variant="outline"
            onClick={handleTest}
            isLoading={testing}
            disabled={!canTest}
            title="Run the query once and show the first rows. Nothing is saved or delivered."
          >
            <FlaskConical className="h-4 w-4" aria-hidden />
            Test query
          </Button>
          <Button onClick={handleSave} isLoading={saving} disabled={!isValid}>
            {isEdit ? 'Save changes' : 'Create report'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Report name" htmlFor="report-name">
          <Input
            id="report-name"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Weekly sales summary"
          />
        </Field>

        <Field label="Source" htmlFor="report-source" hint="Which database the query runs against.">
          <Select
            id="report-source"
            value={sourceKind}
            onChange={e => setSourceKind(e.target.value as ReportSourceKind)}
          >
            <option value="warehouse">A warehouse connection</option>
            {canUseOperations && <option value="operations">Operations database</option>}
          </Select>
        </Field>

        {sourceKind === 'operations' && (
          <Alert tone="warning">
            The operations database holds the application&apos;s own records for every organisation,
            and a query against it is not scoped to yours. Tables holding credentials are refused
            outright.
          </Alert>
        )}

        {needsConnection && (
          <Field label="Warehouse connection" htmlFor="report-connection">
            {connectionsLoaded && connections.length === 0 ? (
              <Alert tone="warning">
                No warehouse connections are configured yet. Add one under Admin &rarr; Warehouses,
                then come back.
              </Alert>
            ) : (
              <Select
                id="report-connection"
                value={warehouseConnectionId}
                onChange={e => setWarehouseConnectionId(Number(e.target.value))}
              >
                <option value="" disabled>
                  Select a connection…
                </option>
                {connections.map(c => (
                  <option key={c.id} value={c.id}>
                    {c.name} ({c.db_type})
                  </option>
                ))}
              </Select>
            )}
          </Field>
        )}

        <Field
          label="SQL query"
          htmlFor="report-sql"
          hint="SELECT only. Writes are rejected, and the query runs in a transaction that is always rolled back."
        >
          <Textarea
            id="report-sql"
            value={sqlQuery}
            onChange={e => setSqlQuery(e.target.value)}
            rows={7}
            spellCheck={false}
            className="font-mono"
            placeholder="SELECT order_id, total FROM marts.orders WHERE created_at >= '2026-01-01'"
          />
        </Field>

        {testError && <Alert tone="danger">{testError}</Alert>}
        {preview && <ReportPreviewPanel preview={preview} />}

        <Field label="Format" htmlFor="report-format">
          <Select id="report-format" value={format} onChange={e => setFormat(e.target.value)}>
            <option value="csv">CSV</option>
            <option value="xlsx">Excel (XLSX)</option>
            <option value="pdf">PDF</option>
          </Select>
        </Field>

        <div className="space-y-3">
          <ToggleRow
            label="Run on a schedule"
            hint={
              isScheduled
                ? 'The report also runs automatically at the times below.'
                : 'On demand only — the report runs when you press Run.'
            }
            checked={isScheduled}
            onCheckedChange={setIsScheduled}
          />

          {isScheduled && (
            <div className="space-y-3 rounded-lg border border-border p-3">
              <Field label="Cron expression" htmlFor="report-cron">
                <Input
                  id="report-cron"
                  value={cron}
                  onChange={e => setCron(e.target.value)}
                  className="font-mono"
                  placeholder="0 6 * * 1"
                />
              </Field>
              <div className="flex flex-wrap gap-1.5">
                {CRON_PRESETS.map(preset => (
                  <button
                    key={preset.value}
                    type="button"
                    onClick={() => setCron(preset.value)}
                    className="rounded-full border border-border px-2.5 py-1 text-xs text-muted-foreground transition-colors hover:border-primary/50 hover:text-foreground"
                  >
                    {preset.label}
                  </button>
                ))}
              </div>
              <ToggleRow
                label="Schedule active"
                hint="Turn off to keep the definition but stop the timer."
                checked={isActive}
                onCheckedChange={setIsActive}
              />
            </div>
          )}
        </div>

        <Field label="Delivery" htmlFor="report-delivery">
          <Select
            id="report-delivery"
            value={deliveryMethod}
            onChange={e => setDeliveryMethod(e.target.value)}
          >
            <option value="download">Store for download</option>
            {/*
              Disabled rather than hidden, so it reads as "not yet" rather than
              "not planned". The API refuses it too: a report saved with a
              delivery that never happens is worse than one that will not save.
            */}
            <option value="email" disabled>
              Email attachment — coming soon
            </option>
            <option value="sftp">SFTP upload</option>
          </Select>
        </Field>

        {deliveryMethod === 'sftp' && (
          <div className="space-y-3 rounded-lg border border-border bg-muted/40 p-3">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              SFTP destination
            </p>
            <div className="grid grid-cols-3 gap-2">
              <div className="col-span-2">
                <Field label="Host" htmlFor="sftp-host">
                  <Input
                    id="sftp-host"
                    value={sftpHost}
                    onChange={e => setSftpHost(e.target.value)}
                    placeholder="sftp.example.com"
                  />
                </Field>
              </div>
              <Field label="Port" htmlFor="sftp-port">
                <Input
                  id="sftp-port"
                  type="number"
                  value={sftpPort}
                  onChange={e => setSftpPort(e.target.value)}
                />
              </Field>
            </div>
            <div className="grid grid-cols-2 gap-2">
              <Field label="Username" htmlFor="sftp-username">
                <Input
                  id="sftp-username"
                  value={sftpUsername}
                  onChange={e => setSftpUsername(e.target.value)}
                />
              </Field>
              <Field
                label="Password"
                htmlFor="sftp-password"
                hint={isEdit ? 'Leave blank to keep the stored password.' : undefined}
              >
                <Input
                  id="sftp-password"
                  type="password"
                  value={sftpPassword}
                  onChange={e => setSftpPassword(e.target.value)}
                />
              </Field>
            </div>
            <Field label="Remote path" htmlFor="sftp-path">
              <Input
                id="sftp-path"
                value={sftpRemotePath}
                onChange={e => setSftpRemotePath(e.target.value)}
                className="font-mono"
              />
            </Field>
          </div>
        )}

        {error && (
          <Alert tone="danger">
            <span className="flex items-start gap-2">
              <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" aria-hidden />
              {error}
            </span>
          </Alert>
        )}
      </div>
    </Modal>
  )
}
