'use client'

/**
 * Collapsible configuration card for the data warehouse connection.
 *
 * Stores credentials encrypted in the AuthProviderConfig table
 * (provider = 'warehouse'). Auth method varies by DB type:
 *   - Snowflake: key pair (private key PEM instead of password)
 *   - BigQuery: JSON service account (full JSON blob instead of host/user/pass)
 *   - All others: host / port / username / password
 *
 * The schemas field accepts multiple values (comma-separated or chip input).
 */
import type { KeyboardEvent } from 'react';
import { useState } from 'react'
import * as Switch from '@radix-ui/react-switch'
import { ChevronDown, ChevronUp, Trash2, X } from 'lucide-react'
import { toast } from 'sonner'
import { cn } from '@/lib/utils'
import { Select } from '@/components/ui'

export interface WarehouseConnectionConfig {
  id?: number
  enabled: boolean
  has_connection_string: boolean
  config: Record<string, string> | null
}

interface WarehouseConnectionCardProps {
  config: WarehouseConnectionConfig | null
  onSave: (data: Record<string, unknown>) => Promise<void>
  onDelete: () => Promise<void>
  onToggle: (enabled: boolean) => Promise<void>
  onTestConnection: () => Promise<{ ok: boolean; error?: string; table_count?: number }>
}

const DB_TYPES = [
  { value: 'postgresql', label: 'PostgreSQL' },
  { value: 'redshift', label: 'Amazon Redshift' },
  { value: 'bigquery', label: 'Google BigQuery' },
  { value: 'snowflake', label: 'Snowflake' },
  { value: 'sqlserver', label: 'SQL Server' },
  { value: 'mysql', label: 'MySQL / MariaDB' },
  { value: 'databricks', label: 'Databricks' },
]

const DEFAULT_PORTS: Record<string, string> = {
  postgresql: '5432',
  redshift: '5439',
  bigquery: '443',
  snowflake: '443',
  sqlserver: '1433',
  mysql: '3306',
  databricks: '443',
}

function parseSchemas(raw: string | undefined): string[] {
  if (!raw) return ['marts']
  try {
    const parsed = JSON.parse(raw)
    if (Array.isArray(parsed)) return parsed as string[]
  } catch {
    // fall through — treat as comma-separated
  }
  return raw.split(',').map(s => s.trim()).filter(Boolean)
}

/** Tag-style multi-value input for schemas. */
function SchemaTagInput({
  schemas,
  onChange,
}: {
  schemas: string[]
  onChange: (s: string[]) => void
}) {
  const [input, setInput] = useState('')

  function addSchema() {
    const val = input.trim()
    if (val && !schemas.includes(val)) {
      onChange([...schemas, val])
    }
    setInput('')
  }

  function handleKeyDown(e: KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Enter' || e.key === ',') {
      e.preventDefault()
      addSchema()
    } else if (e.key === 'Backspace' && !input && schemas.length > 0) {
      onChange(schemas.slice(0, -1))
    }
  }

  return (
    <div className="flex flex-wrap items-center gap-1.5 rounded border border-border-strong px-2 py-1.5 focus-within:ring-2 focus-within:ring-ring min-h-[38px]">
      {schemas.map(s => (
        <span
          key={s}
          className="inline-flex items-center gap-1 rounded bg-primary-subtle px-2 py-0.5 text-xs font-medium text-info-strong"
        >
          {s}
          <button
            type="button"
            onClick={() => onChange(schemas.filter(x => x !== s))}
            className="ml-0.5 text-primary hover:text-primary"
          >
            <X className="h-3 w-3" />
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKeyDown}
        onBlur={addSchema}
        placeholder={schemas.length === 0 ? 'Type schema name, press Enter…' : ''}
        className="flex-1 min-w-[120px] text-sm outline-none bg-transparent"
      />
    </div>
  )
}

export function WarehouseConnectionCard({
  config,
  onSave,
  onDelete,
  onToggle,
  onTestConnection,
}: WarehouseConnectionCardProps) {
  const [expanded, setExpanded] = useState(!config?.id)
  const [saving, setSaving] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [toggling, setToggling] = useState(false)
  const [testing, setTesting] = useState(false)

  const [dbType, setDbType] = useState(config?.config?.['db_type'] ?? 'postgresql')
  const [host, setHost] = useState(config?.config?.['host'] ?? '')
  const [port, setPort] = useState(config?.config?.['port'] ?? '5432')
  const [database, setDatabase] = useState(config?.config?.['database'] ?? '')
  const [schemas, setSchemas] = useState<string[]>(
    parseSchemas(config?.config?.['schemas'] ?? config?.config?.['schema']),
  )
  const [username, setUsername] = useState(config?.config?.['username'] ?? '')
  const [password, setPassword] = useState('')
  const [privateKey, setPrivateKey] = useState('')
  const [privateKeyPassphrase, setPrivateKeyPassphrase] = useState('')
  const [serviceAccountJson, setServiceAccountJson] = useState('')
  const [sslMode, setSslMode] = useState(config?.config?.['ssl_mode'] ?? 'require')
  // Snowflake-specific
  const [account, setAccount] = useState(config?.config?.['account'] ?? '')
  const [warehouse, setWarehouse] = useState(config?.config?.['warehouse'] ?? '')
  const [role, setRole] = useState(config?.config?.['role'] ?? '')
  // BigQuery-specific
  const [projectId, setProjectId] = useState(config?.config?.['project_id'] ?? '')
  const [datasetId, setDatasetId] = useState(config?.config?.['dataset_id'] ?? '')

  const isSnowflake = dbType === 'snowflake'
  const isBigQuery = dbType === 'bigquery'
  const isStandard = !isSnowflake && !isBigQuery

  async function handleSave() {
    if (isSnowflake) {
      if (!account.trim() || !database.trim() || !username.trim()) {
        toast.error('Account, database, and username are required for Snowflake.')
        return
      }
      if (!privateKey && !config?.has_connection_string) {
        toast.error('Private key PEM is required.')
        return
      }
    } else if (isBigQuery) {
      if (!projectId.trim()) {
        toast.error('Project ID is required for BigQuery.')
        return
      }
      if (!serviceAccountJson && !config?.has_connection_string) {
        toast.error('Service account JSON is required.')
        return
      }
    } else {
      if (!host.trim() || !database.trim() || !username.trim()) {
        toast.error('Host, database, and username are required.')
        return
      }
      if (!password && !config?.has_connection_string) {
        toast.error('Password is required.')
        return
      }
    }

    setSaving(true)
    try {
      const baseConfig: Record<string, unknown> = {
        db_type: dbType,
        schemas: JSON.stringify(schemas.length > 0 ? schemas : ['marts']),
      }

      if (isSnowflake) {
        Object.assign(baseConfig, {
          account: account.trim(),
          database: database.trim(),
          username: username.trim(),
          warehouse: warehouse.trim(),
          role: role.trim(),
        })
        await onSave({
          provider: 'warehouse',
          enabled: config?.enabled ?? true,
          ...(privateKey ? { client_secret: privateKey } : {}),
          config: {
            ...baseConfig,
            private_key_passphrase: privateKeyPassphrase,
          },
        })
      } else if (isBigQuery) {
        Object.assign(baseConfig, { project_id: projectId.trim(), dataset_id: datasetId.trim() })
        await onSave({
          provider: 'warehouse',
          enabled: config?.enabled ?? true,
          ...(serviceAccountJson ? { client_secret: serviceAccountJson } : {}),
          config: baseConfig,
        })
      } else {
        Object.assign(baseConfig, {
          host: host.trim(),
          port: port.trim(),
          database: database.trim(),
          username: username.trim(),
          ssl_mode: sslMode,
        })
        await onSave({
          provider: 'warehouse',
          enabled: config?.enabled ?? true,
          ...(password ? { client_secret: password } : {}),
          config: baseConfig,
        })
      }

      setPassword('')
      setPrivateKey('')
      setServiceAccountJson('')
      setExpanded(false)
      toast.success('Warehouse connection saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save warehouse connection.')
    } finally {
      setSaving(false)
    }
  }

  async function handleDelete() {
    setDeleting(true)
    try {
      await onDelete()
      toast.success('Warehouse connection removed.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to remove connection.')
    } finally {
      setDeleting(false)
    }
  }

  async function handleToggle(checked: boolean) {
    setToggling(true)
    try {
      await onToggle(checked)
    } catch {
      toast.error('Failed to update connection status.')
    } finally {
      setToggling(false)
    }
  }

  async function handleTest() {
    setTesting(true)
    try {
      const result = await onTestConnection()
      if (result.ok) {
        toast.success(`Connection successful — ${result.table_count ?? 0} mart tables found.`)
      } else {
        toast.error(`Connection failed: ${result.error ?? 'Unknown error'}`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Test failed.')
    } finally {
      setTesting(false)
    }
  }

  function handleDbTypeChange(type: string) {
    setDbType(type)
    setPort(DEFAULT_PORTS[type] ?? '5432')
  }

  const headerSubtitle = () => {
    if (!config?.config) return 'Used by AI chat and data exports'
    const dbT = config.config['db_type'] ?? 'postgresql'
    if (dbT === 'snowflake') return `snowflake · ${config.config['account'] ?? ''}/${config.config['database'] ?? ''}`
    if (dbT === 'bigquery') return `bigquery · ${config.config['project_id'] ?? ''}`
    return `${dbT} · ${config.config['host'] ?? ''}/${config.config['database'] ?? ''}`
  }

  return (
    <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
      {/* Header */}
      <div className="flex items-center justify-between px-5 py-4">
        <div className="flex items-center gap-3">
          <span className="text-xl">🗄️</span>
          <div>
            <p className="text-sm font-medium text-foreground">Data Warehouse</p>
            <p className="text-xs text-muted-foreground mt-0.5">{headerSubtitle()}</p>
          </div>
        </div>

        <div className="flex items-center gap-3">
          {config?.id && (
            <>
              <button
                type="button"
                onClick={handleTest}
                disabled={testing}
                className="rounded border border-border px-2.5 py-1 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors disabled:opacity-50"
              >
                {testing ? 'Testing…' : 'Test'}
              </button>
              <Switch.Root
                checked={config.enabled}
                disabled={toggling}
                onCheckedChange={handleToggle}
                aria-label={config.enabled ? 'Disable warehouse' : 'Enable warehouse'}
                className={cn(
                  'relative inline-flex h-5 w-9 flex-shrink-0 rounded-full border-2 border-transparent',
                  'transition-colors duration-200 focus:outline-none focus-visible:ring-2 focus-visible:ring-ring',
                  config.enabled ? 'bg-primary' : 'bg-secondary',
                  toggling ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer',
                )}
              >
                <Switch.Thumb
                  className={cn(
                    'pointer-events-none inline-block h-4 w-4 transform rounded-full bg-card shadow',
                    'transition duration-200 ease-in-out',
                    config.enabled ? 'translate-x-4' : 'translate-x-0',
                  )}
                />
              </Switch.Root>
            </>
          )}
          <button
            onClick={() => setExpanded(e => !e)}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
            aria-label={expanded ? 'Collapse' : 'Expand'}
          >
            {expanded ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
          </button>
        </div>
      </div>

      {/* Form */}
      {expanded && (
        <div className="border-t border-border px-5 py-5 space-y-4">
          {/* Database type */}
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Database type</label>
            <Select
              value={dbType}
              onChange={e => handleDbTypeChange(e.target.value)}
            >
              {DB_TYPES.map(t => (
                <option key={t.value} value={t.value}>{t.label}</option>
              ))}
            </Select>
          </div>

          {/* ---- BigQuery: JSON service account ---- */}
          {isBigQuery && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Project ID</label>
                  <input
                    type="text"
                    value={projectId}
                    onChange={e => setProjectId(e.target.value)}
                    placeholder="my-gcp-project"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Dataset ID</label>
                  <input
                    type="text"
                    value={datasetId}
                    onChange={e => setDatasetId(e.target.value)}
                    placeholder="my_dataset"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">
                  Service Account JSON
                  {config?.has_connection_string && (
                    <span className="ml-2 text-xs font-normal text-muted-foreground">(leave blank to keep existing)</span>
                  )}
                </label>
                <textarea
                  value={serviceAccountJson}
                  onChange={e => setServiceAccountJson(e.target.value)}
                  placeholder={config?.has_connection_string ? '(key already stored — paste new JSON to replace)' : '{\n  "type": "service_account",\n  "project_id": "...",\n  ...\n}'}
                  rows={6}
                  className="w-full rounded border border-border-strong px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                />
              </div>
            </>
          )}

          {/* ---- Snowflake: key pair auth ---- */}
          {isSnowflake && (
            <>
              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    Account identifier
                  </label>
                  <input
                    type="text"
                    value={account}
                    onChange={e => setAccount(e.target.value)}
                    placeholder="orgname-accountname"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Database</label>
                  <input
                    type="text"
                    value={database}
                    onChange={e => setDatabase(e.target.value)}
                    placeholder="WAREHOUSE_DB"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
              <div className="grid grid-cols-3 gap-3">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Username</label>
                  <input
                    type="text"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder="BI_USER"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Warehouse</label>
                  <input
                    type="text"
                    value={warehouse}
                    onChange={e => setWarehouse(e.target.value)}
                    placeholder="COMPUTE_WH"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Role</label>
                  <input
                    type="text"
                    value={role}
                    onChange={e => setRole(e.target.value)}
                    placeholder="ANALYST"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">
                  Private key (PEM)
                  {config?.has_connection_string && (
                    <span className="ml-2 text-xs font-normal text-muted-foreground">(leave blank to keep existing)</span>
                  )}
                </label>
                <textarea
                  value={privateKey}
                  onChange={e => setPrivateKey(e.target.value)}
                  placeholder={config?.has_connection_string ? '(key already stored — paste new PEM to replace)' : '-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----'}
                  rows={5}
                  className="w-full rounded border border-border-strong px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-ring resize-none"
                />
              </div>
              <div>
                <label className="block text-sm font-medium text-foreground mb-1">
                  Private key passphrase
                  <span className="ml-2 text-xs font-normal text-muted-foreground">(optional — only if key is encrypted)</span>
                </label>
                <input
                  type="password"
                  value={privateKeyPassphrase}
                  onChange={e => setPrivateKeyPassphrase(e.target.value)}
                  placeholder="passphrase"
                  autoComplete="off"
                  className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </>
          )}

          {/* ---- Standard: host / port / user / pass ---- */}
          {isStandard && (
            <>
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  <label className="block text-sm font-medium text-foreground mb-1">Host</label>
                  <input
                    type="text"
                    value={host}
                    onChange={e => setHost(e.target.value)}
                    placeholder="warehouse.example.com"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Port</label>
                  <input
                    type="text"
                    value={port}
                    onChange={e => setPort(e.target.value)}
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>

              <div>
                <label className="block text-sm font-medium text-foreground mb-1">Database</label>
                <input
                  type="text"
                  value={database}
                  onChange={e => setDatabase(e.target.value)}
                  placeholder="biplatform_warehouse"
                  className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">Username</label>
                  <input
                    type="text"
                    value={username}
                    onChange={e => setUsername(e.target.value)}
                    placeholder="warehouse_reader"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
                <div>
                  <label className="block text-sm font-medium text-foreground mb-1">
                    Password
                    {config?.has_connection_string && (
                      <span className="ml-2 text-xs font-normal text-muted-foreground">(leave blank to keep)</span>
                    )}
                  </label>
                  <input
                    type="password"
                    value={password}
                    onChange={e => setPassword(e.target.value)}
                    placeholder={config?.has_connection_string ? '••••••••' : 'password'}
                    autoComplete="off"
                    className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                  />
                </div>
              </div>

              <div className="max-w-xs">
                <label className="block text-sm font-medium text-foreground mb-1">SSL mode</label>
                <Select
                  value={sslMode}
                  onChange={e => setSslMode(e.target.value)}
                >
                  <option value="require">require</option>
                  <option value="verify-full">verify-full</option>
                  <option value="verify-ca">verify-ca</option>
                  <option value="prefer">prefer</option>
                  <option value="disable">disable</option>
                </Select>
              </div>
            </>
          )}

          {/* Schemas (all db types) */}
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">
              Schemas
              <span className="ml-2 text-xs font-normal text-muted-foreground">
                (marts layers accessible to AI chat and exports — press Enter or comma to add)
              </span>
            </label>
            <SchemaTagInput schemas={schemas} onChange={setSchemas} />
          </div>

          {/* Actions */}
          <div className="flex items-center justify-between pt-2">
            <div>
              {config?.id && (
                <button
                  type="button"
                  onClick={handleDelete}
                  disabled={deleting}
                  className="flex items-center gap-1.5 text-sm text-destructive-strong hover:text-destructive-strong disabled:opacity-50"
                >
                  <Trash2 size={14} />
                  {deleting ? 'Removing…' : 'Remove'}
                </button>
              )}
            </div>
            <button
              type="button"
              onClick={handleSave}
              disabled={saving}
              className="rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover transition-colors disabled:opacity-50"
            >
              {saving ? 'Saving…' : 'Save Connection'}
            </button>
          </div>
        </div>
      )}
    </div>
  )
}
