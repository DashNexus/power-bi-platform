'use client'

/**
 * Warehouse connections management page.
 *
 * Allows admins to create, edit, test, and delete database connections that
 * the platform uses for data transformation and mart queries. Each connection
 * stores credentials encrypted server-side; passwords are write-only in the UI.
 */
import { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import {
  Plus,
  Pencil,
  Trash2,
  Star,
  Zap,
  Database,
  Eye,
  EyeOff,
  Users,
  X,
} from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { ShareResourceDialog } from '@/components/admin/ShareResourceDialog'
import { Select } from '@/components/ui'

// ---------- Types ----------

interface WarehouseConnection {
  id: number
  name: string
  db_type: string
  host: string | null
  port: number | null
  database_name: string | null
  username: string | null
  schemas: string[]
  extra_config: Record<string, string>
  is_default: boolean
  is_active: boolean
  created_at: string
}

type DbType =
  | 'postgresql'
  | 'redshift'
  | 'mysql'
  | 'sqlserver'
  | 'snowflake'
  | 'bigquery'
  | 'databricks'

const DB_TYPE_LABELS: Record<DbType, string> = {
  postgresql: 'PostgreSQL',
  redshift: 'Amazon Redshift',
  mysql: 'MySQL / MariaDB',
  sqlserver: 'SQL Server',
  snowflake: 'Snowflake',
  bigquery: 'BigQuery',
  databricks: 'Databricks',
}

const DB_TYPE_BADGE: Record<DbType, string> = {
  postgresql: 'bg-primary-subtle text-info-strong',
  redshift: 'bg-warning-subtle text-warning-strong',
  mysql: 'bg-orange-100 text-orange-700',
  sqlserver: 'bg-destructive-subtle text-destructive-strong',
  snowflake: 'bg-cyan-100 text-cyan-700',
  bigquery: 'bg-success-subtle text-success-strong',
  databricks: 'bg-purple-100 text-assistant',
}

// Whether the db type uses host/port/database/username/password fields
function isStandardType(t: string): boolean {
  return ['postgresql', 'redshift', 'mysql', 'sqlserver', 'databricks'].includes(t)
}

// ---------- Chip input ----------

interface ChipInputProps {
  tags: string[]
  onAdd: (tag: string) => void
  onRemove: (index: number) => void
  placeholder?: string
}

function ChipInput({ tags, onAdd, onRemove, placeholder }: ChipInputProps) {
  const [input, setInput] = useState('')

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if ((e.key === 'Enter' || e.key === ',') && input.trim()) {
      e.preventDefault()
      onAdd(input.trim().replace(/,+$/, ''))
      setInput('')
    }
  }

  return (
    <div className="flex flex-wrap gap-1 rounded border border-border-strong p-1.5 min-h-[38px] focus-within:ring-2 focus-within:ring-ring focus-within:border-primary">
      {tags.map((t, i) => (
        <span
          key={i}
          className="flex items-center gap-1 rounded bg-primary-subtle px-2 py-0.5 text-xs text-info-strong"
        >
          {t}
          <button
            type="button"
            onClick={() => onRemove(i)}
            className="text-primary hover:text-primary"
          >
            ×
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKey}
        placeholder={tags.length === 0 ? placeholder : ''}
        className="flex-1 min-w-20 text-sm outline-none bg-transparent"
      />
    </div>
  )
}

// ---------- Password field ----------

interface PasswordFieldProps {
  value: string
  onChange: (v: string) => void
  placeholder?: string
}

function PasswordField({ value, onChange, placeholder }: PasswordFieldProps) {
  const [show, setShow] = useState(false)
  return (
    <div className="relative">
      <input
        type={show ? 'text' : 'password'}
        value={value}
        onChange={e => onChange(e.target.value)}
        placeholder={placeholder}
        className="w-full rounded border border-border-strong px-3 py-2 pr-10 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
      <button
        type="button"
        onClick={() => setShow(s => !s)}
        className="absolute right-2.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
      >
        {show ? <EyeOff className="h-4 w-4" /> : <Eye className="h-4 w-4" />}
      </button>
    </div>
  )
}

// ---------- Modal form ----------

interface FormState {
  name: string
  db_type: DbType
  host: string
  port: string
  database_name: string
  username: string
  password: string
  // Snowflake
  account: string
  private_key_pem: string
  private_key_passphrase: string
  // BigQuery
  project_id: string
  service_account_json: string
  schemas: string[]
}

const DEFAULT_FORM: FormState = {
  name: '',
  db_type: 'postgresql',
  host: '',
  port: '',
  database_name: '',
  username: '',
  password: '',
  account: '',
  private_key_pem: '',
  private_key_passphrase: '',
  project_id: '',
  service_account_json: '',
  schemas: [],
}

const DEFAULT_PORTS: Partial<Record<DbType, number>> = {
  postgresql: 5432,
  redshift: 5439,
  mysql: 3306,
  sqlserver: 1433,
  databricks: 443,
}

interface ConnectionModalProps {
  existing: WarehouseConnection | null
  onClose: () => void
  onSaved: () => void
  apiFetch: ReturnType<typeof createClientFetch>
}

function ConnectionModal({ existing, onClose, onSaved, apiFetch }: ConnectionModalProps) {
  const isEdit = existing !== null

  const [form, setForm] = useState<FormState>(() => {
    if (!existing) return DEFAULT_FORM
    return {
      name: existing.name,
      db_type: existing.db_type as DbType,
      host: existing.host ?? '',
      port: existing.port != null ? String(existing.port) : '',
      database_name: existing.database_name ?? '',
      username: existing.username ?? '',
      password: '',
      account: existing.extra_config['account'] ?? '',
      private_key_pem: existing.extra_config['private_key_pem'] ?? '',
      private_key_passphrase: '',
      project_id: existing.extra_config['project_id'] ?? '',
      service_account_json: existing.extra_config['service_account_json'] ?? '',
      schemas: existing.schemas ?? [],
    }
  })
  const [saving, setSaving] = useState(false)

  function set<K extends keyof FormState>(key: K, val: FormState[K]) {
    setForm(f => ({ ...f, [key]: val }))
  }

  function handleTypeChange(t: DbType) {
    set('db_type', t)
    const defaultPort = DEFAULT_PORTS[t]
    if (defaultPort && !form.port) set('port', String(defaultPort))
  }

  async function handleSave() {
    if (!form.name.trim()) return
    setSaving(true)
    try {
      const payload: Record<string, unknown> = {
        name: form.name.trim(),
        db_type: form.db_type,
        schemas: form.schemas,
      }

      if (isStandardType(form.db_type)) {
        if (form.host) payload['host'] = form.host
        if (form.port) payload['port'] = Number(form.port)
        if (form.database_name) payload['database_name'] = form.database_name
        if (form.username) payload['username'] = form.username
        if (form.password) payload['password'] = form.password
      } else if (form.db_type === 'snowflake') {
        const extra: Record<string, string> = {}
        if (form.account) extra['account'] = form.account
        if (form.private_key_pem) extra['private_key_pem'] = form.private_key_pem
        if (form.private_key_passphrase) extra['private_key_passphrase'] = form.private_key_passphrase
        if (form.database_name) payload['database_name'] = form.database_name
        if (form.username) payload['username'] = form.username
        payload['extra_config'] = extra
      } else if (form.db_type === 'bigquery') {
        const extra: Record<string, string> = {}
        if (form.project_id) extra['project_id'] = form.project_id
        if (form.service_account_json) extra['service_account_json'] = form.service_account_json
        payload['extra_config'] = extra
      }

      if (isEdit) {
        await apiFetch(`/warehouses/${existing.id}`, {
          method: 'PUT',
          body: JSON.stringify(payload),
        })
        toast.success('Connection updated.')
      } else {
        await apiFetch('/warehouses', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        toast.success('Connection created.')
      }
      onSaved()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save connection.')
    } finally {
      setSaving(false)
    }
  }

  const field = (
    label: string,
    key: keyof FormState,
    opts?: { placeholder?: string; type?: string },
  ) => (
    <div>
      <label className="block text-xs font-medium text-muted-foreground mb-1">{label}</label>
      <input
        type={opts?.type ?? 'text'}
        value={form[key] as string}
        onChange={e => set(key, e.target.value as FormState[typeof key])}
        placeholder={opts?.placeholder}
        className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
      />
    </div>
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg rounded-lg bg-card p-6 shadow-xl max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between mb-4">
          <h3 className="text-base font-semibold text-foreground">
            {isEdit ? 'Edit Connection' : 'Add Connection'}
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="space-y-3">
          {/* Name */}
          {field('Name', 'name', { placeholder: 'Production Warehouse' })}

          {/* Type */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Type</label>
            <Select
              value={form.db_type}
              onChange={e => handleTypeChange(e.target.value as DbType)}
            >
              {(Object.entries(DB_TYPE_LABELS) as [DbType, string][]).map(([k, v]) => (
                <option key={k} value={k}>{v}</option>
              ))}
            </Select>
          </div>

          {/* Standard type fields */}
          {isStandardType(form.db_type) && (
            <>
              <div className="grid grid-cols-3 gap-3">
                <div className="col-span-2">
                  {field('Host', 'host', { placeholder: 'db.example.com' })}
                </div>
                <div>
                  {field('Port', 'port', { placeholder: '5432' })}
                </div>
              </div>
              {field('Database', 'database_name', { placeholder: 'mydb' })}
              {field('Username', 'username', { placeholder: 'readonly_user' })}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Password {isEdit && <span className="text-muted-foreground">(leave blank to keep existing)</span>}
                </label>
                <PasswordField
                  value={form.password}
                  onChange={v => set('password', v)}
                  placeholder={isEdit ? '••••••••' : 'password'}
                />
              </div>
            </>
          )}

          {/* Snowflake fields */}
          {form.db_type === 'snowflake' && (
            <>
              {field('Account Identifier', 'account', { placeholder: 'xy12345.us-east-1' })}
              {field('Database', 'database_name', { placeholder: 'PROD_DB' })}
              {field('Username', 'username', { placeholder: 'svc_user' })}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Private Key PEM {isEdit && <span className="text-muted-foreground">(leave blank to keep existing)</span>}
                </label>
                <textarea
                  value={form.private_key_pem}
                  onChange={e => set('private_key_pem', e.target.value)}
                  rows={5}
                  placeholder="-----BEGIN RSA PRIVATE KEY-----&#10;..."
                  className="w-full rounded border border-border-strong px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Private Key Passphrase{' '}
                  <span className="text-muted-foreground">(optional — only if key is encrypted)</span>
                </label>
                <PasswordField
                  value={form.private_key_passphrase}
                  onChange={v => set('private_key_passphrase', v)}
                  placeholder="passphrase"
                />
              </div>
            </>
          )}

          {/* BigQuery fields */}
          {form.db_type === 'bigquery' && (
            <>
              {field('Project ID', 'project_id', { placeholder: 'my-gcp-project' })}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">
                  Service Account JSON {isEdit && <span className="text-muted-foreground">(leave blank to keep existing)</span>}
                </label>
                <textarea
                  value={form.service_account_json}
                  onChange={e => set('service_account_json', e.target.value)}
                  rows={6}
                  placeholder={'{\n  "type": "service_account",\n  ...\n}'}
                  className="w-full rounded border border-border-strong px-3 py-2 text-xs font-mono focus:outline-none focus:ring-2 focus:ring-ring"
                />
              </div>
            </>
          )}

          {/* Schemas (all types) */}
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Schemas <span className="text-muted-foreground">(press Enter or comma to add)</span>
            </label>
            <ChipInput
              tags={form.schemas}
              onAdd={tag => set('schemas', [...form.schemas, tag])}
              onRemove={i => set('schemas', form.schemas.filter((_, idx) => idx !== i))}
              placeholder="public, analytics, marts…"
            />
          </div>
        </div>

        <div className="flex justify-end gap-2 pt-4">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded border px-4 py-2 text-sm hover:bg-accent disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || !form.name.trim()}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          >
            {saving ? 'Saving…' : isEdit ? 'Save Changes' : 'Add Connection'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------- Main page ----------

export default function WarehousesPage() {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [connections, setConnections] = useState<WarehouseConnection[]>([])
  const [loading, setLoading] = useState(true)
  const [showModal, setShowModal] = useState(false)
  const [editingConn, setEditingConn] = useState<WarehouseConnection | null>(null)
  const [testingId, setTestingId] = useState<number | null>(null)
  const [actingId, setActingId] = useState<number | null>(null)
  const [shareConn, setShareConn] = useState<WarehouseConnection | null>(null)

  const loadConnections = useCallback(async () => {
    if (!session?.user?.access_token) return
    try {
      const data = await apiFetch<WarehouseConnection[]>('/warehouses')
      setConnections(data)
    } catch {
      toast.error('Failed to load warehouse connections.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  useEffect(() => {
    void loadConnections()
  }, [loadConnections])

  async function handleTest(conn: WarehouseConnection) {
    setTestingId(conn.id)
    try {
      const result = await apiFetch<{ ok: boolean; table_count?: number; error?: string }>(
        `/warehouses/${conn.id}/test`,
        { method: 'POST' },
      )
      if (result.ok) {
        toast.success(
          `Connected successfully.${result.table_count != null ? ` Found ${result.table_count} tables.` : ''}`,
        )
      } else {
        toast.error(`Connection failed: ${result.error ?? 'Unknown error'}`)
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Test failed.')
    } finally {
      setTestingId(null)
    }
  }

  async function handleSetDefault(conn: WarehouseConnection) {
    setActingId(conn.id)
    try {
      await apiFetch(`/warehouses/${conn.id}/set-default`, { method: 'POST' })
      toast.success(`${conn.name} is now the default connection.`)
      await loadConnections()
    } catch {
      toast.error('Failed to set default.')
    } finally {
      setActingId(null)
    }
  }

  async function handleDelete(conn: WarehouseConnection) {
    if (!confirm(`Delete "${conn.name}"? This cannot be undone.`)) return
    setActingId(conn.id)
    try {
      await apiFetch(`/warehouses/${conn.id}`, { method: 'DELETE' })
      toast.success(`${conn.name} deleted.`)
      setConnections(prev => prev.filter(c => c.id !== conn.id))
    } catch {
      toast.error('Failed to delete connection.')
    } finally {
      setActingId(null)
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Loading warehouse connections…
      </div>
    )
  }

  return (
    <>
      {(showModal || editingConn) && (
        <ConnectionModal
          existing={editingConn}
          onClose={() => {
            setShowModal(false)
            setEditingConn(null)
          }}
          onSaved={() => void loadConnections()}
          apiFetch={apiFetch}
        />
      )}

      <div>
        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Warehouse Connections</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Manage the database connections used for data transformation and analytics queries.
            </p>
          </div>
          <button
            onClick={() => {
              setEditingConn(null)
              setShowModal(true)
            }}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
          >
            <Plus className="h-4 w-4" />
            Add Connection
          </button>
        </div>

        {connections.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-card py-20 text-center">
            <Database className="mb-3 h-10 w-10 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground">No warehouse connections yet.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Add a connection to start running transformations and analytics.
            </p>
            <button
              onClick={() => {
                setEditingConn(null)
                setShowModal(true)
              }}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
            >
              <Plus className="h-4 w-4" />
              Add Connection
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
            <table className="min-w-full divide-y divide-border text-sm">
              <thead className="bg-muted">
                <tr>
                  {['Name', 'Type', 'Host / Account', 'Schemas', 'Status', ''].map(h => (
                    <th
                      key={h}
                      scope="col"
                      className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {connections.map(conn => {
                  const badgeClass =
                    DB_TYPE_BADGE[conn.db_type as DbType] ?? 'bg-muted text-muted-foreground'
                  const label =
                    DB_TYPE_LABELS[conn.db_type as DbType] ?? conn.db_type

                  const hostDisplay =
                    conn.db_type === 'snowflake'
                      ? (conn.extra_config?.['account'] ?? '—')
                      : conn.db_type === 'bigquery'
                        ? (conn.extra_config?.['project_id'] ?? '—')
                        : conn.host
                          ? `${conn.host}${conn.port ? `:${conn.port}` : ''}`
                          : '—'

                  return (
                    <tr key={conn.id} className="hover:bg-accent">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2">
                          <p className="font-medium text-foreground">{conn.name}</p>
                          {conn.is_default && (
                            <span className="inline-flex items-center rounded-full bg-primary-subtle px-2 py-0.5 text-xs font-medium text-info-strong">
                              default
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${badgeClass}`}
                        >
                          {label}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        {hostDisplay}
                      </td>
                      <td className="px-4 py-3 text-xs text-muted-foreground">
                        {conn.schemas.length > 0 ? conn.schemas.join(', ') : '—'}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
 conn.is_active
 ? 'bg-success-subtle text-success-strong'
 : 'bg-muted text-muted-foreground'
 }`}
                        >
                          {conn.is_active ? 'active' : 'inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => void handleTest(conn)}
                            disabled={testingId === conn.id}
                            title={testingId === conn.id ? 'Testing…' : 'Test connection'}
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-yellow-600 disabled:opacity-40"
                          >
                            <Zap className="h-4 w-4" />
                          </button>
                          {!conn.is_default && (
                            <button
                              onClick={() => void handleSetDefault(conn)}
                              disabled={actingId === conn.id}
                              title="Set as default"
                              className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-primary disabled:opacity-40"
                            >
                              <Star className="h-4 w-4" />
                            </button>
                          )}
                          <button
                            onClick={() => setShareConn(conn)}
                            title="Share with roles"
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          >
                            <Users className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => setEditingConn(conn)}
                            title="Edit"
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          >
                            <Pencil className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => void handleDelete(conn)}
                            disabled={actingId === conn.id}
                            title="Delete"
                            className="rounded p-1.5 text-red-400 transition-colors hover:bg-destructive-subtle hover:text-destructive-strong disabled:opacity-40"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      {shareConn && (
        <ShareResourceDialog
          resourceLabel="Warehouse"
          resourceName={shareConn.name}
          permissionsPath={`/admin/warehouses/${shareConn.id}/permissions`}
          apiFetch={apiFetch}
          onClose={() => setShareConn(null)}
        />
      )}
    </>
  )
}
