'use client'

/**
 * Data dictionary management page.
 *
 * Three-panel layout: warehouse selector + schema/table tree on the left,
 * column-level entries in the main panel. Descriptions are edited inline;
 * PII flags and tags are toggled per row. AI generation auto-populates
 * descriptions using Claude via the backend. Supports search, export,
 * column refresh, per-field change history with revert, and schema/table
 * exclusions to hide items from the tree.
 */
import { useState, useEffect, useCallback, useRef } from 'react'
import { createPortal } from 'react-dom'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import {
  ChevronDown,
  ChevronRight,
  ChevronLeft,
  Table2,
  Sparkles,
  RefreshCw,
  Loader2,
  X,
  Key,
  Search,
  Download,
  Layers,
  Eye,
  EyeOff,
  Clock,
  RotateCcw,
  Trash2,
  Users,
  PanelLeft,
  Database,
} from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { ShareResourceDialog } from '@/components/admin/ShareResourceDialog'
import {
  ResourceToolbar,
  useResourceView,
  filterBySearch,
} from '@/components/admin/ResourceExplorer'
import { Select } from '@/components/ui'

// ---------- Types ----------

interface TableRef {
  schema: string
  name: string
}

interface DataDictionaryEntry {
  id: number
  schema_name: string
  table_name: string
  column_name: string | null
  description: string | null
  data_type: string | null
  is_pii: boolean
  tags: string[]
  ai_generated: boolean
  updated_at: string
  is_pk: boolean
  fk_schema: string | null
  fk_table: string | null
  fk_column: string | null
  relationship_type: string | null
}

interface SchemaInfo {
  name: string
  tables: { name: string; object_type?: 'table' | 'view'; excluded?: boolean }[]
  excluded?: boolean
}

interface WarehouseOption {
  id: number
  name: string
  schemas: string[]
}

interface Exclusion {
  id: number
  warehouse_connection_id: number
  schema_name: string
  table_name: string | null
  created_at: string
}

interface ChangeLogEntry {
  id: number
  entry_id: number | null
  field_name: string
  old_value: string | null
  new_value: string | null
  changed_by_user_id: number | null
  changed_by_display_name: string | null
  changed_at: string
}

// ---------- Tag chip input (inline) ----------

interface TagEditorProps {
  tags: string[]
  onChange: (tags: string[]) => void
}

function TagEditor({ tags, onChange }: TagEditorProps) {
  const [input, setInput] = useState('')

  function handleKey(e: React.KeyboardEvent<HTMLInputElement>) {
    if ((e.key === 'Enter' || e.key === ',') && input.trim()) {
      e.preventDefault()
      const tag = input.trim().replace(/,+$/, '')
      if (!tags.includes(tag)) onChange([...tags, tag])
      setInput('')
    }
  }

  return (
    <div className="flex flex-wrap gap-1 items-center">
      {tags.map((t, i) => (
        <span
          key={i}
          className="flex items-center gap-0.5 rounded bg-muted px-1.5 py-0.5 text-xs text-foreground"
        >
          {t}
          <button
            type="button"
            onClick={() => onChange(tags.filter((_, idx) => idx !== i))}
            className="text-muted-foreground hover:text-foreground"
          >
            <X className="h-2.5 w-2.5" />
          </button>
        </span>
      ))}
      <input
        value={input}
        onChange={e => setInput(e.target.value)}
        onKeyDown={handleKey}
        placeholder={tags.length === 0 ? 'add tag…' : ''}
        className="text-xs outline-none bg-transparent min-w-16 text-muted-foreground placeholder:text-muted-foreground"
      />
    </div>
  )
}

// ---------- Keys modal ----------

interface KeysModalProps {
  entry: DataDictionaryEntry
  allTables: TableRef[]
  warehouseConnectionId: number | null
  onClose: () => void
  onSave: (patch: Partial<DataDictionaryEntry>) => Promise<void>
}

function KeysModal({ entry, allTables, warehouseConnectionId, onClose, onSave }: KeysModalProps) {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [isPk, setIsPk] = useState(entry.is_pk)
  const toComposite = (schema: string | null, table: string | null) =>
    table ? `${schema ?? ''}|${table}` : ''
  const [fkComposite, setFkComposite] = useState(
    toComposite(entry.fk_schema, entry.fk_table)
  )
  const [fkColumn, setFkColumn] = useState(entry.fk_column ?? '')
  const [relationshipType, setRelationshipType] = useState(entry.relationship_type ?? 'many_to_one')
  const [saving, setSaving] = useState(false)
  const [fkColumns, setFkColumns] = useState<string[]>([])
  const [loadingFkCols, setLoadingFkCols] = useState(false)
  const [syncingFromWarehouse, setSyncingFromWarehouse] = useState(false)

  async function handleSyncFromWarehouse() {
    if (!warehouseConnectionId || !entry.schema_name || !entry.table_name) return
    setSyncingFromWarehouse(true)
    try {
      await apiFetch('/data-dictionary/populate', {
        method: 'POST',
        body: JSON.stringify({
          warehouse_connection_id: warehouseConnectionId,
          schema_name: entry.schema_name,
          table_name: entry.table_name,
        }),
      })
      toast.success('Keys refreshed from warehouse. Reload the dictionary to see updates.')
    } catch {
      toast.error('Warehouse key sync failed.')
    } finally {
      setSyncingFromWarehouse(false)
    }
  }

  const isColumnLevel = entry.column_name !== null

  const sepIdx = fkComposite.indexOf('|')
  const fkSchema = sepIdx >= 0 ? fkComposite.slice(0, sepIdx) || null : null
  const fkTable = sepIdx >= 0 ? fkComposite.slice(sepIdx + 1) : ''

  // Load columns for the selected FK target table from the data dictionary
  useEffect(() => {
    if (!fkTable || !warehouseConnectionId) {
      setFkColumns([])
      return
    }
    setLoadingFkCols(true)
    const params: Record<string, string | number> = {
      warehouse_connection_id: warehouseConnectionId,
      table_name: fkTable,
    }
    if (fkSchema) params.schema_name = fkSchema
    apiFetch<DataDictionaryEntry[]>('/data-dictionary', { searchParams: params })
      .then(data => {
        const cols = data
          .filter(e => e.column_name !== null)
          .map(e => e.column_name as string)
          .sort()
        setFkColumns(cols)
      })
      .catch(() => {})
      .finally(() => setLoadingFkCols(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [fkTable, fkSchema, warehouseConnectionId])

  function handleFkTableChange(val: string) {
    setFkComposite(val)
    setFkColumn('')
    setFkColumns([])
  }

  async function handleSave() {
    setSaving(true)
    try {
      const patch: Partial<DataDictionaryEntry> = { is_pk: isPk }
      if (isColumnLevel) {
        patch.fk_schema = fkTable ? (fkSchema ?? '') : ''
        patch.fk_table = fkTable || ''
        patch.fk_column = fkTable ? fkColumn.trim() || null : ''
        patch.relationship_type = fkTable ? relationshipType : null
      }
      await onSave(patch)
      onClose()
    } finally {
      setSaving(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-sm rounded-lg bg-card p-6 shadow-xl space-y-4">
        <div className="flex items-center justify-between">
          <h3 className="text-base font-semibold text-foreground">
            Column Keys — <span className="font-mono text-foreground">{entry.column_name}</span>
          </h3>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        <label className="flex items-center gap-2 cursor-pointer">
          <input
            type="checkbox"
            checked={isPk}
            onChange={e => setIsPk(e.target.checked)}
            className="h-4 w-4 rounded border-border-strong text-yellow-500 focus:ring-yellow-400"
          />
          <span className="text-sm text-foreground">Primary Key</span>
        </label>

        {isColumnLevel && (
          <div className="space-y-2">
            <p className="text-xs font-medium text-muted-foreground">Foreign Key Reference</p>
            <Select
              value={fkComposite}
              onChange={e => handleFkTableChange(e.target.value)}
            >
              <option value="">— no foreign key —</option>
              {allTables.map(t => {
                const val = `${t.schema}|${t.name}`
                return (
                  <option key={val} value={val}>
                    {t.schema ? `${t.schema}.${t.name}` : t.name}
                  </option>
                )
              })}
              {fkTable && !allTables.some(t => t.name === fkTable && (t.schema || '') === (fkSchema || '')) && (
                <option value={fkComposite} disabled>
                  {fkSchema ? `${fkSchema}.${fkTable}` : fkTable} (not in dictionary)
                </option>
              )}
            </Select>
            {/* FK column — dropdown when columns are available from the DD, else free text */}
            {fkTable && (
              loadingFkCols ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-1">
                  <Loader2 className="h-3 w-3 animate-spin" /> Loading columns…
                </div>
              ) : fkColumns.length > 0 ? (
                <Select
                  value={fkColumn}
                  onChange={e => setFkColumn(e.target.value)}
                >
                  <option value="">— select column —</option>
                  {fkColumns.map(col => (
                    <option key={col} value={col}>{col}</option>
                  ))}
                </Select>
              ) : (
                <input
                  value={fkColumn}
                  onChange={e => setFkColumn(e.target.value)}
                  placeholder="referenced column (e.g. id)"
                  className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
                />
              )
            )}
          </div>
        )}

        {isColumnLevel && fkTable && (
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Relationship Type</label>
            <Select
              value={relationshipType}
              onChange={e => setRelationshipType(e.target.value)}
            >
              <option value="many_to_one">Many → One</option>
              <option value="one_to_one">One → One</option>
              <option value="one_to_many">One → Many</option>
              <option value="many_to_many">Many → Many</option>
            </Select>
          </div>
        )}

        <div className="flex items-center justify-between pt-2">
          <button
            type="button"
            onClick={() => void handleSyncFromWarehouse()}
            disabled={syncingFromWarehouse || !warehouseConnectionId}
            title="Re-read PK/FK annotations for this table from the live warehouse schema"
            className="inline-flex items-center gap-1.5 text-xs text-muted-foreground hover:text-foreground disabled:opacity-40"
          >
            {syncingFromWarehouse ? (
              <Loader2 className="h-3 w-3 animate-spin" />
            ) : (
              <RefreshCw className="h-3 w-3" />
            )}
            Sync from warehouse
          </button>
          <div className="flex gap-2">
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
              disabled={saving}
              className="inline-flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
            >
              {saving && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Save
            </button>
          </div>
        </div>
      </div>
    </div>,
    document.body
  )
}

// ---------- History modal ----------

interface HistoryModalProps {
  entry: DataDictionaryEntry
  onClose: () => void
  onRevert: (entryId: number, logId: number) => Promise<void>
}

function HistoryModal({ entry, onClose, onRevert }: HistoryModalProps) {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)
  const [logs, setLogs] = useState<ChangeLogEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [revertingId, setRevertingId] = useState<number | null>(null)

  useEffect(() => {
    apiFetch<ChangeLogEntry[]>(`/data-dictionary/${entry.id}/changes`)
      .then(setLogs)
      .catch(() => toast.error('Failed to load history.'))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [entry.id])

  function formatValue(raw: string | null): string {
    if (raw === null) return '—'
    try {
      const parsed: unknown = JSON.parse(raw)
      if (parsed === null) return '—'
      if (Array.isArray(parsed)) return parsed.length ? parsed.join(', ') : '(empty)'
      return String(parsed)
    } catch {
      return raw
    }
  }

  async function handleRevert(logId: number) {
    setRevertingId(logId)
    try {
      await onRevert(entry.id, logId)
      // Reload the log after reverting
      const updated = await apiFetch<ChangeLogEntry[]>(`/data-dictionary/${entry.id}/changes`)
      setLogs(updated)
      toast.success('Reverted successfully.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Revert failed.')
    } finally {
      setRevertingId(null)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg rounded-lg bg-card shadow-xl flex flex-col max-h-[80vh]">
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-border">
          <div>
            <h3 className="text-base font-semibold text-foreground">Change History</h3>
            <p className="text-xs text-muted-foreground font-mono mt-0.5">
              {entry.column_name ?? <span className="italic">table-level</span>}
            </p>
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto p-4">
          {loading ? (
            <div className="flex items-center justify-center py-10">
              <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
            </div>
          ) : logs.length === 0 ? (
            <p className="text-sm text-muted-foreground text-center py-10">No changes recorded yet.</p>
          ) : (
            <div className="space-y-2">
              {logs.map(log => (
                <div
                  key={log.id}
                  className="rounded border border-border bg-muted px-3 py-2.5 text-xs"
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <span className="font-medium text-foreground">{log.field_name}</span>
                      <div className="mt-1 flex items-center gap-1.5 flex-wrap">
                        <span className="line-through text-destructive max-w-[200px] truncate">
                          {formatValue(log.old_value)}
                        </span>
                        <span className="text-muted-foreground">→</span>
                        <span className="text-success-strong max-w-[200px] truncate">
                          {formatValue(log.new_value)}
                        </span>
                      </div>
                    </div>
                    <button
                      type="button"
                      onClick={() => void handleRevert(log.id)}
                      disabled={revertingId === log.id}
                      className="shrink-0 inline-flex items-center gap-1 rounded border border-border-strong px-2 py-1 text-xs text-muted-foreground hover:bg-card disabled:opacity-50"
                      title="Revert to this value"
                    >
                      {revertingId === log.id ? (
                        <Loader2 className="h-3 w-3 animate-spin" />
                      ) : (
                        <RotateCcw className="h-3 w-3" />
                      )}
                      Revert
                    </button>
                  </div>
                  <div className="mt-1.5 text-muted-foreground">
                    {new Date(log.changed_at).toLocaleString()}
                    {(log.changed_by_display_name || log.changed_by_user_id) && (
                      <span className="ml-1">
                        · {log.changed_by_display_name ?? `user #${log.changed_by_user_id}`}
                      </span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ---------- Search dialog ----------

interface SearchResult {
  id: number
  schema_name: string
  table_name: string
  column_name: string | null
  description: string | null
  tags: string[]
  data_type: string | null
}

interface SearchDialogProps {
  warehouseConnectionId: number
  onNavigate: (schema: string, table: string, column: string | null) => void
  onClose: () => void
}

function SearchDialog({ warehouseConnectionId, onNavigate, onClose }: SearchDialogProps) {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [query, setQuery] = useState('')
  const [semantic, setSemantic] = useState(false)
  const [results, setResults] = useState<SearchResult[]>([])
  const [loading, setLoading] = useState(false)
  const debounceRef = useRef<ReturnType<typeof setTimeout> | null>(null)
  const inputRef = useRef<HTMLInputElement>(null)

  useEffect(() => {
    inputRef.current?.focus()
  }, [])

  useEffect(() => {
    if (debounceRef.current) clearTimeout(debounceRef.current)
    if (!query.trim()) {
      setResults([])
      return
    }
    debounceRef.current = setTimeout(() => {
      setLoading(true)
      apiFetch<SearchResult[]>('/data-dictionary/search', {
        method: 'POST',
        body: JSON.stringify({ query: query.trim(), warehouse_connection_id: warehouseConnectionId, semantic }),
      })
        .then(data => setResults(data))
        .catch(() => {})
        .finally(() => setLoading(false))
    }, 300)
    return () => {
      if (debounceRef.current) clearTimeout(debounceRef.current)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, semantic, warehouseConnectionId])

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === 'Escape') onClose()
  }

  return createPortal(
    <div
      className="fixed inset-0 z-50 flex items-start justify-center pt-24 bg-black/50"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="w-full max-w-xl rounded-xl bg-card shadow-2xl overflow-hidden">
        {/* Search bar */}
        <div className="flex items-center gap-2 px-4 py-3 border-b">
          {loading
            ? <Loader2 className="h-4 w-4 text-muted-foreground animate-spin shrink-0" />
            : <Search className="h-4 w-4 text-muted-foreground shrink-0" />
          }
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={e => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search columns, tables, descriptions…"
            className="flex-1 text-sm bg-transparent outline-none text-foreground placeholder:text-muted-foreground"
          />
          <button
            type="button"
            onClick={() => setSemantic(s => !s)}
            title={semantic ? 'AI search on — click to use keyword search' : 'Switch to AI semantic search'}
            className={`rounded px-2 py-1 text-xs font-medium flex items-center gap-1 transition-colors ${
 semantic ? 'bg-purple-100 text-assistant' : 'text-muted-foreground hover:bg-accent'
 }`}
          >
            <Sparkles className="h-3 w-3" />
            AI
          </button>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-4 w-4" />
          </button>
        </div>

        {/* Results */}
        <div className="max-h-80 overflow-y-auto">
          {results.length === 0 && query.trim() && !loading && (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">No results found.</p>
          )}
          {results.length === 0 && !query.trim() && (
            <p className="px-4 py-8 text-center text-sm text-muted-foreground">
              Start typing to search all columns and descriptions.
            </p>
          )}
          {results.map(r => (
            <button
              key={r.id}
              type="button"
              onClick={() => {
                onNavigate(r.schema_name, r.table_name, r.column_name)
                onClose()
              }}
              className="w-full text-left px-4 py-3 hover:bg-accent border-b last:border-0 group"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono text-xs text-foreground group-hover:text-foreground">
                  {r.schema_name}.{r.table_name}{r.column_name ? `.${r.column_name}` : ''}
                </span>
                {r.data_type && (
                  <span className="text-xs text-muted-foreground shrink-0">{r.data_type}</span>
                )}
              </div>
              {r.description && (
                <p className="mt-0.5 text-xs text-muted-foreground line-clamp-2">{r.description}</p>
              )}
              {r.tags.length > 0 && (
                <div className="mt-1 flex gap-1 flex-wrap">
                  {r.tags.map(t => (
                    <span key={t} className="rounded bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">{t}</span>
                  ))}
                </div>
              )}
            </button>
          ))}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ---------- Revert modal ----------

interface RevertChange {
  entry_id: number
  schema_name: string
  table_name: string
  column_name: string | null
  field_name: string
  current_value: string | null
  target_value: string | null
}

interface RevertResult {
  changes: RevertChange[]
  total: number
}

interface RevertModalProps {
  warehouseConnectionId: number
  onClose: () => void
  onReverted: () => void
}

function RevertModal({ warehouseConnectionId, onClose, onReverted }: RevertModalProps) {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [asOf, setAsOf] = useState('')
  const [preview, setPreview] = useState<RevertResult | null>(null)
  const [loadingPreview, setLoadingPreview] = useState(false)
  const [applying, setApplying] = useState(false)

  async function handlePreview() {
    if (!asOf) return
    setLoadingPreview(true)
    setPreview(null)
    try {
      const result = await apiFetch<RevertResult>('/data-dictionary/revert-to-point-in-time', {
        method: 'POST',
        body: JSON.stringify({ warehouse_connection_id: warehouseConnectionId, as_of: new Date(asOf).toISOString(), dry_run: true }),
      })
      setPreview(result)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Preview failed.')
    } finally {
      setLoadingPreview(false)
    }
  }

  async function handleApply() {
    if (!asOf) return
    setApplying(true)
    try {
      await apiFetch('/data-dictionary/revert-to-point-in-time', {
        method: 'POST',
        body: JSON.stringify({ warehouse_connection_id: warehouseConnectionId, as_of: new Date(asOf).toISOString(), dry_run: false }),
      })
      toast.success('Revert applied. Changes have been logged.')
      onReverted()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Revert failed.')
    } finally {
      setApplying(false)
    }
  }

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-lg rounded-lg bg-card shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b">
          <h3 className="text-base font-semibold text-foreground flex items-center gap-2">
            <RotateCcw className="h-4 w-4 text-muted-foreground" />
            Revert to Point in Time
          </h3>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        <div className="px-6 py-4 space-y-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">Revert all descriptions, tags, and keys to how they were at:</label>
            <input
              type="datetime-local"
              value={asOf}
              onChange={e => { setAsOf(e.target.value); setPreview(null) }}
              className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>

          {preview && (
            <div>
              <p className="text-xs font-medium text-muted-foreground mb-2">
                {preview.total === 0
                  ? 'No changes — the dictionary already matches that point in time.'
                  : `${preview.total} field${preview.total === 1 ? '' : 's'} would be changed:`
                }
              </p>
              {preview.changes.length > 0 && (
                <div className="max-h-48 overflow-y-auto rounded border border-border divide-y text-xs">
                  {preview.changes.map((c, i) => (
                    <div key={i} className="px-3 py-2">
                      <span className="font-mono text-foreground">
                        {c.schema_name}.{c.table_name}{c.column_name ? `.${c.column_name}` : ''} — {c.field_name}
                      </span>
                      <div className="mt-0.5 text-muted-foreground">
                        <span className="line-through text-red-400">{c.current_value ?? '—'}</span>
                        {' → '}
                        <span className="text-success-strong">{c.target_value ?? '—'}</span>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}

          {preview && preview.total > 0 && (
            <p className="text-xs text-warning-strong">
              This cannot be undone directly, though all changes are logged and can be reverted again.
            </p>
          )}
        </div>

        <div className="flex justify-end gap-2 px-6 py-4 border-t bg-muted">
          <button
            type="button"
            onClick={onClose}
            disabled={applying}
            className="rounded border px-4 py-2 text-sm hover:bg-card disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handlePreview()}
            disabled={!asOf || loadingPreview || applying}
            className="inline-flex items-center gap-2 rounded border border-primary/40 bg-primary-subtle px-4 py-2 text-sm font-medium text-info-strong hover:bg-primary-subtle disabled:opacity-50"
          >
            {loadingPreview && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
            Preview
          </button>
          {preview && preview.total > 0 && (
            <button
              type="button"
              onClick={() => void handleApply()}
              disabled={applying}
              className="inline-flex items-center gap-2 rounded bg-destructive px-4 py-2 text-sm font-medium text-white hover:bg-destructive/90 disabled:opacity-50"
            >
              {applying && <Loader2 className="h-3.5 w-3.5 animate-spin" />}
              Apply Revert
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body
  )
}

// ---------- Entry row ----------

interface EntryRowProps {
  entry: DataDictionaryEntry
  onSave: (id: number, patch: Partial<DataDictionaryEntry>) => Promise<void>
  onDelete: (id: number) => void
  onShowHistory: (entry: DataDictionaryEntry) => void
  searchQuery?: string
  allTables: TableRef[]
  warehouseConnectionId: number | null
}

function EntryRow({ entry, onSave, onDelete, onShowHistory, searchQuery = '', allTables, warehouseConnectionId }: EntryRowProps) {
  const [editing, setEditing] = useState(false)
  const [draft, setDraft] = useState(entry.description ?? '')
  const [saving, setSaving] = useState(false)
  const [keysModalOpen, setKeysModalOpen] = useState(false)
  const textareaRef = useRef<HTMLTextAreaElement>(null)

  const sq = searchQuery.toLowerCase()
  const isMatch = sq && (
    (entry.column_name?.toLowerCase().includes(sq)) ||
    (entry.data_type?.toLowerCase().includes(sq)) ||
    (entry.description?.toLowerCase().includes(sq))
  )

  async function commitDescription() {
    setEditing(false)
    const val = draft.trim() || null
    if (val === (entry.description ?? null)) return
    setSaving(true)
    try {
      await onSave(entry.id, { description: val })
    } finally {
      setSaving(false)
    }
  }

  async function togglePii() {
    await onSave(entry.id, { is_pii: !entry.is_pii })
  }

  async function handleTagsChange(tags: string[]) {
    await onSave(entry.id, { tags })
  }

  const isTableLevel = entry.column_name === null

  return (
    <>
      {keysModalOpen && (
        <KeysModal
          entry={entry}
          allTables={allTables}
          warehouseConnectionId={warehouseConnectionId}
          onClose={() => setKeysModalOpen(false)}
          onSave={patch => onSave(entry.id, patch)}
        />
      )}
      <tr className={`align-top ${isMatch ? 'bg-warning-subtle' : 'hover:bg-accent'}`}>
        {/* Column name */}
        <td className="px-4 py-2.5 font-mono text-xs">
          {isTableLevel ? (
            <span className="rounded bg-primary-subtle px-2 py-0.5 text-xs font-medium text-info-strong">
              Table
            </span>
          ) : (
            <span className="text-foreground">{entry.column_name}</span>
          )}
        </td>

        {/* Type */}
        <td className="px-4 py-2.5 font-mono text-xs text-muted-foreground">
          {entry.data_type ?? '—'}
        </td>

        {/* Keys */}
        <td className="px-4 py-2.5">
          {!isTableLevel && (
            <div className="flex items-center gap-1 flex-wrap">
              {entry.is_pk && (
                <span className="inline-flex items-center gap-0.5 rounded bg-warning-subtle pl-1.5 pr-0.5 py-0.5 text-xs font-medium text-warning-strong">
                  <Key className="h-2.5 w-2.5" />
                  PK
                  <button
                    type="button"
                    onClick={() => void onSave(entry.id, { is_pk: false })}
                    className="ml-0.5 rounded hover:bg-yellow-100"
                    title="Remove primary key"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              )}
              {entry.fk_table && (
                <span className="inline-flex items-center rounded bg-primary-subtle pl-1.5 pr-0.5 py-0.5 text-xs font-medium text-info-strong">
                  FK → {entry.fk_table}{entry.fk_column ? `.${entry.fk_column}` : ''}
                  <button
                    type="button"
                    onClick={() => void onSave(entry.id, { fk_schema: '', fk_table: '', fk_column: null, relationship_type: null })}
                    className="ml-0.5 rounded hover:bg-primary-subtle"
                    title="Remove foreign key"
                  >
                    <X className="h-2.5 w-2.5" />
                  </button>
                </span>
              )}
              <button
                type="button"
                onClick={() => setKeysModalOpen(true)}
                className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-muted-foreground"
                title="Edit key metadata"
              >
                <Key className="h-3 w-3" />
              </button>
            </div>
          )}
        </td>

        {/* Description (inline edit) */}
        <td className="px-4 py-2.5 min-w-0 w-full max-w-sm">
          {editing ? (
            <textarea
              ref={textareaRef}
              value={draft}
              onChange={e => setDraft(e.target.value)}
              onBlur={() => void commitDescription()}
              autoFocus
              rows={2}
              className="w-full rounded border border-primary/60 px-2 py-1 text-xs focus:outline-none resize-none"
            />
          ) : (
            <button
              type="button"
              className="text-left w-full"
              onClick={() => {
                setDraft(entry.description ?? '')
                setEditing(true)
              }}
            >
              {saving ? (
                <span className="flex items-center gap-1 text-xs text-muted-foreground">
                  <Loader2 className="h-3 w-3 animate-spin" /> Saving…
                </span>
              ) : entry.description ? (
                <span className="text-xs text-foreground hover:text-foreground">
                  {entry.description}
                </span>
              ) : (
                <span className="text-xs text-muted-foreground italic hover:text-muted-foreground">
                  Click to add description…
                </span>
              )}
            </button>
          )}
        </td>

        {/* PII toggle */}
        <td className="px-4 py-2.5 text-center">
          <input
            type="checkbox"
            checked={entry.is_pii}
            onChange={() => void togglePii()}
            className="h-3.5 w-3.5 rounded border-border-strong text-destructive-strong focus:ring-red-500"
          />
        </td>

        {/* Tags */}
        <td className="px-4 py-2.5">
          <TagEditor tags={entry.tags} onChange={tags => void handleTagsChange(tags)} />
        </td>

        {/* AI badge */}
        <td className="px-4 py-2.5 text-center">
          {entry.ai_generated && (
            <span className="inline-flex items-center rounded bg-muted px-1.5 py-0.5 text-xs font-medium text-muted-foreground">
              AI
            </span>
          )}
        </td>

        {/* History + delete buttons */}
        <td className="px-3 py-2.5 text-center">
          <div className="flex items-center gap-1 justify-center">
            <button
              type="button"
              onClick={() => onShowHistory(entry)}
              className="rounded p-0.5 text-muted-foreground hover:bg-accent hover:text-muted-foreground"
              title="View change history"
            >
              <Clock className="h-3.5 w-3.5" />
            </button>
            <button
              type="button"
              onClick={() => onDelete(entry.id)}
              className="rounded p-0.5 text-muted-foreground hover:bg-destructive-subtle hover:text-red-500"
              title="Delete entry"
            >
              <Trash2 className="h-3.5 w-3.5" />
            </button>
          </div>
        </td>
      </tr>
    </>
  )
}

// ---------- Main page ----------

export default function DataDictionaryPage() {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [warehouses, setWarehouses] = useState<WarehouseOption[]>([])
  const [selectedWarehouseId, setSelectedWarehouseId] = useState<number | null>(null)
  const [schemas, setSchemas] = useState<SchemaInfo[]>([])
  const [expandedSchemas, setExpandedSchemas] = useState<Set<string>>(new Set())
  const [selectedSchema, setSelectedSchema] = useState<string | null>(null)
  const [selectedTable, setSelectedTable] = useState<string | null>(null)
  const [entries, setEntries] = useState<DataDictionaryEntry[]>([])
  const [loadingEntries, setLoadingEntries] = useState(false)
  const [generatingAi, setGeneratingAi] = useState(false)
  const [populating, setPopulating] = useState(false)
  const [populatingAll, setPopulatingAll] = useState(false)
  const [populatingWarehouse, setPopulatingWarehouse] = useState(false)
  const [generatingAiAll, setGeneratingAiAll] = useState(false)
  const [loadingSchemas, setLoadingSchemas] = useState(false)

  // Search state
  const [treeSearch, setTreeSearch] = useState('')
  const [columnSearch, setColumnSearch] = useState('')

  // Export dropdown
  const [showExport, setShowExport] = useState(false)

  // Exclusions
  const [exclusions, setExclusions] = useState<Exclusion[]>([])
  const [showHidden, setShowHidden] = useState(false)

  // History modal
  const [historyEntry, setHistoryEntry] = useState<DataDictionaryEntry | null>(null)

  // Search dialog + revert modal + share dialog
  const [searchOpen, setSearchOpen] = useState(false)
  const [revertOpen, setRevertOpen] = useState(false)
  const [shareOpen, setShareOpen] = useState(false)

  // Sidebar collapse
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)

  // Warehouse picker view (cards/list) shown when no warehouse is selected.
  const warehouseView = useResourceView('data-dict-warehouses', 'card')
  // Table/view browser (cards/list) shown when a warehouse but no table is selected.
  const tableView = useResourceView('data-dict-tables', 'card')
  const [collapsedSchemas, setCollapsedSchemas] = useState<Set<string>>(new Set())

  function toggleBrowserSchema(name: string) {
    setCollapsedSchemas(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  // Derived exclusion lookups
  const excludedSchemas = new Set(
    exclusions.filter(e => e.table_name === null).map(e => e.schema_name)
  )
  const excludedTables = new Set(
    exclusions.filter(e => e.table_name !== null).map(e => `${e.schema_name}.${e.table_name}`)
  )

  // Cmd+K / Ctrl+K opens the search dialog when a warehouse is selected
  useEffect(() => {
    function onKeyDown(e: KeyboardEvent) {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        if (selectedWarehouseId) setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [selectedWarehouseId])

  // Load warehouses on mount — no auto-selection, user picks explicitly
  useEffect(() => {
    if (!session?.user?.access_token) return
    apiFetch<WarehouseOption[]>('/warehouses')
      .then(data => setWarehouses(data))
      .catch(() => toast.error('Failed to load warehouses.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  function mergeSchemaTree(
    dictTree: { name: string; tables: { name: string }[]; excluded?: boolean }[],
    configuredSchemas: string[],
  ): SchemaInfo[] {
    // Key by uppercase so "DIMENSIONS" and "dimensions" collapse to one entry.
    // dictTree wins for canonical name (it reflects what the warehouse actually returned).
    const map = new Map<string, { canonical: string; tables: { name: string }[] }>()
    for (const s of configuredSchemas) {
      if (s) map.set(s.toUpperCase(), { canonical: s, tables: [] })
    }
    for (const s of dictTree) {
      const seen = new Set<string>()
      const dedupedTables = s.tables.filter(t => {
        if (seen.has(t.name)) return false
        seen.add(t.name)
        return true
      })
      // dictTree's casing is authoritative — overwrite any config-sourced entry
      map.set(s.name.toUpperCase(), { canonical: s.name, tables: dedupedTables })
    }
    return Array.from(map.values())
      .sort((a, b) => a.canonical.localeCompare(b.canonical))
      .map(({ canonical, tables }) => ({ name: canonical, tables }))
  }

  const reloadSchemaTree = useCallback(async (warehouseId: number) => {
    try {
      const data = await apiFetch<{ name: string; tables: { name: string }[]; excluded?: boolean }[]>(
        '/data-dictionary/tree',
        { searchParams: { warehouse_connection_id: warehouseId, include_excluded: true } },
      )
      const wh = warehouses.find(w => w.id === warehouseId)
      setSchemas(mergeSchemaTree(data, wh?.schemas ?? []))
    } catch {
      // best-effort background refresh
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [warehouses])

  const reloadExclusions = useCallback(async (warehouseId: number) => {
    try {
      const data = await apiFetch<Exclusion[]>('/data-dictionary/exclusions', {
        searchParams: { warehouse_connection_id: warehouseId },
      })
      setExclusions(data)
    } catch {
      // best-effort
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // Load schema tree and exclusions when warehouse changes
  useEffect(() => {
    if (!selectedWarehouseId || !session?.user?.access_token) return
    setLoadingSchemas(true)
    setSchemas([])
    setSelectedSchema(null)
    setSelectedTable(null)
    setEntries([])
    setExclusions([])
    const wh = warehouses.find(w => w.id === selectedWarehouseId)
    const wid = selectedWarehouseId
    Promise.all([
      apiFetch<{ name: string; tables: { name: string }[] }[]>(
        '/data-dictionary/tree',
        { searchParams: { warehouse_connection_id: wid, include_excluded: true } },
      ),
      apiFetch<Exclusion[]>('/data-dictionary/exclusions', {
        searchParams: { warehouse_connection_id: wid },
      }),
    ])
      .then(([treeData, exclData]) => {
        const merged = mergeSchemaTree(treeData, wh?.schemas ?? [])
        setSchemas(merged)
        setExclusions(exclData)
        if (merged.length > 0) {
          setExpandedSchemas(new Set([merged[0].name]))
        }
      })
      .catch(() => toast.error('Failed to load schema tree.'))
      .finally(() => setLoadingSchemas(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWarehouseId])

  const loadEntries = useCallback(async () => {
    if (!selectedWarehouseId || !selectedSchema || !selectedTable) return
    setLoadingEntries(true)
    try {
      const data = await apiFetch<DataDictionaryEntry[]>('/data-dictionary', {
        searchParams: {
          warehouse_connection_id: selectedWarehouseId,
          schema_name: selectedSchema,
          table_name: selectedTable,
        },
      })
      setEntries(data)
    } catch {
      toast.error('Failed to load dictionary entries.')
    } finally {
      setLoadingEntries(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWarehouseId, selectedSchema, selectedTable])

  useEffect(() => {
    void loadEntries()
    setColumnSearch('')
  }, [loadEntries])

  function selectTable(schema: string, table: string) {
    setSelectedSchema(schema)
    setSelectedTable(table)
  }

  function handleNavigateToResult(schema: string, table: string, column: string | null) {
    setSelectedSchema(schema)
    setSelectedTable(table)
    setColumnSearch(column ?? '')
  }

  function toggleSchema(name: string) {
    setExpandedSchemas(prev => {
      const next = new Set(prev)
      if (next.has(name)) next.delete(name)
      else next.add(name)
      return next
    })
  }

  async function toggleExclusion(schemaName: string, tableName: string | null, e: React.MouseEvent) {
    e.stopPropagation()
    if (!selectedWarehouseId) return
    const key = tableName ? `${schemaName}.${tableName}` : schemaName
    const isCurrentlyExcluded = tableName
      ? excludedTables.has(key)
      : excludedSchemas.has(key)

    if (isCurrentlyExcluded) {
      const excl = exclusions.find(ex =>
        ex.schema_name === schemaName && ex.table_name === (tableName ?? null)
      )
      if (!excl) return
      // Optimistic remove — update state immediately, roll back on failure
      setExclusions(prev => prev.filter(ex => ex.id !== excl.id))
      try {
        await apiFetch(`/data-dictionary/exclusions/${excl.id}`, { method: 'DELETE' })
      } catch {
        toast.error('Failed to unhide.')
        await reloadExclusions(selectedWarehouseId)
      }
    } else {
      // Optimistic add — insert a placeholder immediately, replace with real row on success
      const tempId = -(Date.now())
      const tempExcl: Exclusion = {
        id: tempId,
        warehouse_connection_id: selectedWarehouseId,
        schema_name: schemaName,
        table_name: tableName,
        created_at: new Date().toISOString(),
      }
      setExclusions(prev => [...prev, tempExcl])
      try {
        const created = await apiFetch<Exclusion>('/data-dictionary/exclusions', {
          method: 'POST',
          body: JSON.stringify({
            warehouse_connection_id: selectedWarehouseId,
            schema_name: schemaName,
            table_name: tableName,
          }),
        })
        setExclusions(prev => prev.map(ex => ex.id === tempId ? created : ex))
      } catch {
        toast.error('Failed to hide.')
        setExclusions(prev => prev.filter(ex => ex.id !== tempId))
      }
    }
  }

  async function handleSaveEntry(id: number, patch: Partial<DataDictionaryEntry>) {
    const prev = entries.find(e => e.id === id)
    if (!prev) return
    setEntries(es => es.map(e => (e.id === id ? { ...e, ...patch } : e)))
    try {
      const updated = await apiFetch<DataDictionaryEntry>(`/data-dictionary/${id}`, {
        method: 'PUT',
        body: JSON.stringify(patch),
      })
      setEntries(es => es.map(e => (e.id === id ? updated : e)))
    } catch (err) {
      setEntries(es => es.map(e => (e.id === id ? prev : e)))
      toast.error(err instanceof Error ? err.message : 'Failed to save.')
    }
  }

  async function handleDeleteEntry(id: number) {
    const prev = entries.find(e => e.id === id)
    if (!prev) return
    setEntries(es => es.filter(e => e.id !== id))
    try {
      await apiFetch(`/data-dictionary/${id}`, { method: 'DELETE' })
    } catch (err) {
      setEntries(es => [...es, prev].sort((a, b) => (a.column_name ?? '').localeCompare(b.column_name ?? '')))
      toast.error(err instanceof Error ? err.message : 'Failed to delete entry.')
    }
  }

  async function handleRevertEntry(entryId: number, logId: number) {
    const updated = await apiFetch<DataDictionaryEntry>(
      `/data-dictionary/${entryId}/revert/${logId}`,
      { method: 'POST' }
    )
    setEntries(es => es.map(e => (e.id === entryId ? updated : e)))
  }

  async function handlePopulate() {
    if (!selectedWarehouseId || !selectedSchema || !selectedTable) return
    setPopulating(true)
    try {
      await apiFetch('/data-dictionary/populate', {
        method: 'POST',
        body: JSON.stringify({
          warehouse_connection_id: selectedWarehouseId,
          schema_name: selectedSchema,
          table_name: selectedTable,
        }),
      })
      toast.success(entries.length > 0 ? 'Columns refreshed.' : 'Columns populated.')
      await loadEntries()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Populate failed.')
    } finally {
      setPopulating(false)
    }
  }

  async function handleGenerateAi() {
    if (!selectedWarehouseId || !selectedSchema || !selectedTable) return
    setGeneratingAi(true)
    try {
      await apiFetch('/data-dictionary/generate-ai', {
        method: 'POST',
        body: JSON.stringify({
          warehouse_connection_id: selectedWarehouseId,
          schema_name: selectedSchema,
          table_name: selectedTable,
        }),
      })
      toast.success('AI descriptions generated.')
      await loadEntries()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'AI generation failed.')
    } finally {
      setGeneratingAi(false)
    }
  }

  async function handleRefreshWarehouse() {
    if (!selectedWarehouseId) return
    setPopulatingWarehouse(true)
    try {
      const result = await apiFetch<{
        schemas_processed: number
        tables_processed: number
        total_created: number
        total_skipped: number
      }>('/data-dictionary/populate-warehouse', {
        method: 'POST',
        body: JSON.stringify({ warehouse_connection_id: selectedWarehouseId }),
      })
      toast.success(
        `Refreshed ${result.schemas_processed} schemas — ${result.tables_processed} tables, ${result.total_created} entries created.`,
      )
      await reloadSchemaTree(selectedWarehouseId)
      if (selectedTable) await loadEntries()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Warehouse refresh failed.')
    } finally {
      setPopulatingWarehouse(false)
    }
  }

  async function handlePopulateAll() {
    if (!selectedWarehouseId || !selectedSchema) return
    setPopulatingAll(true)
    try {
      const result = await apiFetch<{ tables_processed: number; total_created: number; total_skipped: number }>(
        '/data-dictionary/populate-all',
        {
          method: 'POST',
          body: JSON.stringify({ warehouse_connection_id: selectedWarehouseId, schema_name: selectedSchema }),
        },
      )
      toast.success(
        `Populated ${result.tables_processed} tables — ${result.total_created} entries created, ${result.total_skipped} updated.`,
      )
      await reloadSchemaTree(selectedWarehouseId)
      if (selectedTable) await loadEntries()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Populate all failed.')
    } finally {
      setPopulatingAll(false)
    }
  }

  async function handleGenerateAiAll() {
    if (!selectedWarehouseId || !selectedSchema) return
    setGeneratingAiAll(true)
    try {
      const result = await apiFetch<{
        tables_processed: number
        tables_succeeded: number
        tables_failed: number
        entries_updated: number
      }>('/data-dictionary/generate-ai-all', {
        method: 'POST',
        body: JSON.stringify({ warehouse_connection_id: selectedWarehouseId, schema_name: selectedSchema }),
      })
      const msg =
        result.tables_failed > 0
          ? `AI generated for ${result.tables_succeeded}/${result.tables_processed} tables — ${result.tables_failed} failed.`
          : `AI generated for all ${result.tables_processed} tables.`
      toast.success(msg)
      if (selectedTable) await loadEntries()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'AI generation failed.')
    } finally {
      setGeneratingAiAll(false)
    }
  }

  function handleExportCsv() {
    if (!entries.length) return
    const header = '"schema","table","column","type","description","is_pk","fk_ref","relationship_type","is_pii","tags","ai_generated"'
    const rows = entries.map(e => {
      const fkRef = [e.fk_schema, e.fk_table, e.fk_column].filter(Boolean).join('.')
      return [
        e.schema_name,
        e.table_name,
        e.column_name ?? '',
        e.data_type ?? '',
        e.description ?? '',
        e.is_pk ? 'true' : 'false',
        fkRef,
        e.relationship_type ?? '',
        e.is_pii ? 'true' : 'false',
        e.tags.join(';'),
        e.ai_generated ? 'true' : 'false',
      ].map(v => `"${String(v).replace(/"/g, '""')}"`).join(',')
    })
    const csv = [header, ...rows].join('\n')
    const blob = new Blob([csv], { type: 'text/csv;charset=utf-8;' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.download = `${selectedSchema ?? 'data'}.${selectedTable ?? 'dictionary'}.csv`
    a.href = url
    a.click()
    URL.revokeObjectURL(url)
  }

  function handleExportJson() {
    if (!entries.length) return
    const blob = new Blob([JSON.stringify(entries, null, 2)], { type: 'application/json' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.download = `${selectedSchema ?? 'data'}.${selectedTable ?? 'dictionary'}.json`
    a.href = url
    a.click()
    URL.revokeObjectURL(url)
  }

  const hasSelection = selectedSchema && selectedTable

  const allTables: TableRef[] = schemas.flatMap(s =>
    s.tables.map(t => ({ schema: s.name, name: t.name }))
  )

  // Prev/next table navigation for the entered-table view.
  const currentTableIndex = hasSelection
    ? allTables.findIndex(t => t.schema === selectedSchema && t.name === selectedTable)
    : -1
  const prevTable = currentTableIndex > 0 ? allTables[currentTableIndex - 1] : null
  const nextTable =
    currentTableIndex >= 0 && currentTableIndex < allTables.length - 1
      ? allTables[currentTableIndex + 1]
      : null

  function exitTable() {
    setSelectedTable(null)
    setSelectedSchema(null)
  }

  // Filter schema tree by search and exclusion visibility
  const treeQ = treeSearch.toLowerCase()
  const filteredSchemas = schemas
    .filter(s => showHidden || !excludedSchemas.has(s.name))
    .map(s => ({
      ...s,
      tables: s.tables
        .filter(t => showHidden || !excludedTables.has(`${s.name}.${t.name}`))
        .filter(t =>
          !treeQ ||
          t.name.toLowerCase().includes(treeQ) ||
          s.name.toLowerCase().includes(treeQ)
        ),
    }))
    .filter(s =>
      !treeQ || s.tables.length > 0 || s.name.toLowerCase().includes(treeQ)
    )

  // Filter entries by column search
  const colQ = columnSearch.toLowerCase()
  const filteredEntries = colQ
    ? entries.filter(e =>
        e.column_name?.toLowerCase().includes(colQ) ||
        e.data_type?.toLowerCase().includes(colQ) ||
        e.description?.toLowerCase().includes(colQ)
      )
    : entries

  const hiddenCount = exclusions.length

  return (
    <div className="flex h-[calc(100vh-8rem)] overflow-hidden">
      {/* Left panel: warehouse selector + schema/table tree — collapsible */}
      <div className={`flex-shrink-0 flex flex-col border-r border-border bg-muted overflow-y-auto transition-all duration-200 ${sidebarCollapsed ? 'w-0 overflow-hidden' : 'w-48'}`}>
        {/* Warehouse selector */}
        <div className="p-3 border-b border-border">
          <Select
            value={selectedWarehouseId ?? ''}
            onChange={e => setSelectedWarehouseId(e.target.value ? Number(e.target.value) : null)} size="sm"
          >
            <option value="">— select a warehouse —</option>
            {warehouses.map(w => (
              <option key={w.id} value={w.id}>{w.name}</option>
            ))}
          </Select>
        </div>

        {/* Tree search + hidden toggle */}
        <div className="px-2 py-2 border-b border-border space-y-1.5">
          <div className="relative">
            <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
            <input
              value={treeSearch}
              onChange={e => setTreeSearch(e.target.value)}
              placeholder="Filter tables…"
              className="w-full pl-5 pr-2 py-1 text-xs rounded border border-border bg-card focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
          {hiddenCount > 0 && (
            <button
              type="button"
              onClick={() => setShowHidden(v => !v)}
              className="inline-flex w-full items-center gap-1 text-xs text-muted-foreground hover:text-foreground"
            >
              {showHidden ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
              {showHidden ? `Hide ${hiddenCount} excluded` : `Show ${hiddenCount} hidden`}
            </button>
          )}
        </div>

        {/* Schema/table tree */}
        <div className="flex-1 py-2">
          {loadingSchemas ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
            </div>
          ) : filteredSchemas.length === 0 ? (
            <p className="px-3 py-4 text-xs text-muted-foreground">
              {treeSearch ? 'No matches.' : 'No schemas found.'}
            </p>
          ) : (
            filteredSchemas.map((schema, si) => {
              const schemaIsExcluded = excludedSchemas.has(schema.name)
              return (
                <div key={`${si}-${schema.name}`}>
                  <div className="group flex w-full items-center gap-1 px-3 py-1.5 hover:bg-accent">
                    <button
                      type="button"
                      onClick={() => toggleSchema(schema.name)}
                      className="flex flex-1 items-center gap-1 min-w-0"
                    >
                      {expandedSchemas.has(schema.name) ? (
                        <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                      ) : (
                        <ChevronRight className="h-3 w-3 shrink-0 text-muted-foreground" />
                      )}
                      <span className={`truncate text-xs font-semibold uppercase tracking-wide ${schemaIsExcluded ? 'text-muted-foreground line-through' : 'text-muted-foreground'}`}>
                        {schema.name}
                      </span>
                    </button>
                    <button
                      type="button"
                      onClick={e => void toggleExclusion(schema.name, null, e)}
                      className="shrink-0 hidden group-hover:block text-muted-foreground hover:text-muted-foreground"
                      title={schemaIsExcluded ? 'Unhide schema' : 'Hide schema'}
                    >
                      {schemaIsExcluded ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                    </button>
                  </div>
                  {expandedSchemas.has(schema.name) &&
                    schema.tables.map((table, ti) => {
                      const tableKey = `${schema.name}.${table.name}`
                      const tableIsExcluded = excludedTables.has(tableKey)
                      return (
                        <div
                          key={`${ti}-${table.name}`}
                          className={`group flex items-center pr-2 transition-colors ${
                            selectedSchema === schema.name && selectedTable === table.name
                              ? 'bg-primary-subtle'
                              : 'hover:bg-accent'
                          }`}
                        >
                          <button
                            type="button"
                            onClick={() => selectTable(schema.name, table.name)}
                            className={`flex flex-1 items-center pl-6 py-1.5 text-xs truncate min-w-0 ${
 selectedSchema === schema.name && selectedTable === table.name
 ? 'text-info-strong font-medium'
 : tableIsExcluded
 ? 'text-muted-foreground line-through'
 : 'text-muted-foreground'
 }`}
                          >
                            <span className="truncate">{table.name}</span>
                            {table.object_type === 'view' && (
                              <span className="ml-1 shrink-0 rounded bg-purple-100 px-1 py-px text-[10px] font-medium text-assistant">
                                view
                              </span>
                            )}
                          </button>
                          <button
                            type="button"
                            onClick={e => void toggleExclusion(schema.name, table.name, e)}
                            className="shrink-0 hidden group-hover:block text-muted-foreground hover:text-muted-foreground ml-1"
                            title={tableIsExcluded ? 'Unhide table' : 'Hide table'}
                          >
                            {tableIsExcluded ? <Eye className="h-3 w-3" /> : <EyeOff className="h-3 w-3" />}
                          </button>
                        </div>
                      )
                    })}
                </div>
              )
            })
          )}
        </div>
      </div>

      {/* Main panel */}
      <div className="flex-1 flex flex-col overflow-hidden min-w-0">
        {/* Warehouse toolbar */}
        <div className="flex items-center gap-2 px-3 py-2 border-b border-border bg-card shrink-0">
          <button
            type="button"
            onClick={() => setSidebarCollapsed(v => !v)}
            title={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className="rounded p-1 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <PanelLeft className="h-4 w-4" />
          </button>
          {selectedWarehouseId && (
            <>
              <div className="w-px h-4 bg-secondary" />
              <button
                type="button"
                onClick={() => void handleRefreshWarehouse()}
                disabled={populatingWarehouse}
                className="inline-flex items-center gap-1.5 rounded border border-border-strong px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
                title="Re-introspect all schemas and refresh column metadata"
              >
                {populatingWarehouse ? (
                  <Loader2 className="h-3 w-3 animate-spin" />
                ) : (
                  <RefreshCw className="h-3 w-3" />
                )}
                {populatingWarehouse ? 'Refreshing…' : 'Refresh warehouse'}
              </button>
              <button
                type="button"
                onClick={() => setRevertOpen(true)}
                className="inline-flex items-center gap-1.5 rounded border border-border-strong px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
                title="Revert all annotations to a point in time"
              >
                <RotateCcw className="h-3 w-3" />
                Revert to time
              </button>
              <button
                type="button"
                onClick={() => setShareOpen(true)}
                className="inline-flex items-center gap-1.5 rounded border border-border-strong px-2.5 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
                title="Configure who can view this data dictionary"
              >
                <Users className="h-3 w-3" />
                Share
              </button>
            </>
          )}
        </div>

        {/* Panel header: title + schema/table actions */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-border bg-card gap-3">
          <div className="flex items-center gap-2 shrink-0">
            {hasSelection && (
              <div className="flex items-center gap-0.5">
                <button
                  type="button"
                  onClick={exitTable}
                  title="Back to tables"
                  className="inline-flex items-center gap-1 rounded border border-border-strong px-2 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
                >
                  <ChevronLeft className="h-3.5 w-3.5" /> Tables
                </button>
                <button
                  type="button"
                  disabled={!prevTable}
                  onClick={() => prevTable && selectTable(prevTable.schema, prevTable.name)}
                  title={prevTable ? `Previous: ${prevTable.schema}.${prevTable.name}` : 'No previous table'}
                  className="rounded border border-border-strong p-1.5 text-muted-foreground hover:bg-accent disabled:opacity-40"
                >
                  <ChevronLeft className="h-3.5 w-3.5" />
                </button>
                <button
                  type="button"
                  disabled={!nextTable}
                  onClick={() => nextTable && selectTable(nextTable.schema, nextTable.name)}
                  title={nextTable ? `Next: ${nextTable.schema}.${nextTable.name}` : 'No next table'}
                  className="rounded border border-border-strong p-1.5 text-muted-foreground hover:bg-accent disabled:opacity-40"
                >
                  <ChevronRight className="h-3.5 w-3.5" />
                </button>
              </div>
            )}
            <h1 className="text-lg font-semibold text-foreground">
              {hasSelection ? (
                <span className="font-mono">
                  {selectedSchema}
                  <span className="text-muted-foreground">.</span>
                  {selectedTable}
                </span>
              ) : selectedSchema ? (
                <span className="font-mono text-foreground">{selectedSchema}</span>
              ) : (
                'Data Dictionary'
              )}
            </h1>
          </div>
          {selectedSchema && (
            <div className="flex items-center gap-2 flex-wrap">
              {/* Global dictionary search */}
              {selectedWarehouseId && (
                <button
                  type="button"
                  onClick={() => setSearchOpen(true)}
                  className="inline-flex items-center gap-1.5 rounded border border-border-strong px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
                  title="Search all columns and descriptions (⌘K)"
                >
                  <Search className="h-3.5 w-3.5" />
                  Search
                  <kbd className="ml-1 rounded bg-muted px-1 py-0.5 text-[10px] font-mono text-muted-foreground">⌘K</kbd>
                </button>
              )}
              {/* Bulk schema actions */}
              <button
                type="button"
                onClick={() => void handlePopulateAll()}
                disabled={populatingAll}
                className="inline-flex items-center gap-1.5 rounded border border-border-strong px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
              >
                {populatingAll ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Layers className="h-3.5 w-3.5" />
                )}
                Populate all
              </button>
              <button
                type="button"
                onClick={() => void handleGenerateAiAll()}
                disabled={generatingAiAll}
                className="inline-flex items-center gap-1.5 rounded border border-purple-300 px-3 py-1.5 text-xs font-medium text-assistant hover:bg-purple-50 disabled:opacity-50"
              >
                {generatingAiAll ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                AI for all
              </button>

              {hasSelection && <div className="h-4 w-px bg-secondary" />}

              {/* Table-specific actions */}
              {hasSelection && (
                <>
              {/* Column search */}
              <div className="relative">
                <Search className="absolute left-2 top-1/2 -translate-y-1/2 h-3 w-3 text-muted-foreground pointer-events-none" />
                <input
                  value={columnSearch}
                  onChange={e => setColumnSearch(e.target.value)}
                  placeholder="Search columns…"
                  className="pl-6 pr-2 py-1.5 text-xs rounded border border-border-strong focus:outline-none focus:ring-1 focus:ring-ring w-40"
                />
                {columnSearch && (
                  <button
                    type="button"
                    onClick={() => setColumnSearch('')}
                    className="absolute right-1.5 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="h-3 w-3" />
                  </button>
                )}
              </div>

              {/* Populate / Refresh columns */}
              <button
                type="button"
                onClick={() => void handlePopulate()}
                disabled={populating}
                title="Re-introspect the warehouse table to refresh column list, PK flags, and FK references"
                className="inline-flex items-center gap-1.5 rounded border border-border-strong px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
              >
                {populating ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <RefreshCw className="h-3.5 w-3.5" />
                )}
                {entries.length > 0 ? 'Refresh columns' : 'Populate columns'}
              </button>

              {/* Refresh Keys / Relations — re-runs warehouse introspection, updating PK/FK annotations */}
              {entries.length > 0 && (
                <button
                  type="button"
                  onClick={() => void handlePopulate()}
                  disabled={populating}
                  title="Re-sync primary key and foreign key annotations from the live warehouse schema"
                  className="inline-flex items-center gap-1.5 rounded border border-border-strong px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
                >
                  {populating ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <Key className="h-3.5 w-3.5" />
                  )}
                  Refresh Keys
                </button>
              )}

              {/* Generate with AI */}
              <button
                type="button"
                onClick={() => void handleGenerateAi()}
                disabled={generatingAi}
                className="inline-flex items-center gap-1.5 rounded bg-purple-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-purple-700 disabled:opacity-50"
              >
                {generatingAi ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin" />
                ) : (
                  <Sparkles className="h-3.5 w-3.5" />
                )}
                Generate with AI
              </button>

              {/* Export dropdown */}
              {entries.length > 0 && (
                <div className="relative">
                  <button
                    type="button"
                    onClick={() => setShowExport(v => !v)}
                    className="inline-flex items-center gap-1.5 rounded border border-border-strong px-3 py-1.5 text-xs font-medium text-muted-foreground hover:bg-accent"
                  >
                    <Download className="h-3.5 w-3.5" />
                    Export
                  </button>
                  {showExport && (
                    <>
                      <div className="fixed inset-0 z-10" onClick={() => setShowExport(false)} />
                      <div className="absolute right-0 top-full mt-1 w-36 rounded-md border border-border bg-card shadow-lg z-20">
                        <button
                          type="button"
                          onClick={() => { handleExportCsv(); setShowExport(false) }}
                          className="w-full text-left px-3 py-2 text-xs text-foreground hover:bg-accent rounded-t-md"
                        >
                          Export as CSV
                        </button>
                        <button
                          type="button"
                          onClick={() => { handleExportJson(); setShowExport(false) }}
                          className="w-full text-left px-3 py-2 text-xs text-foreground hover:bg-accent rounded-b-md border-t border-border"
                        >
                          Export as JSON
                        </button>
                      </div>
                    </>
                  )}
                </div>
              )}
                </>
              )}
            </div>
          )}
        </div>

        {/* Table body */}
        <div className="flex-1 overflow-y-auto">
          {!selectedWarehouseId ? (
            <div className="p-4">
              <h2 className="mb-1 text-lg font-semibold text-foreground">Warehouses</h2>
              <p className="mb-4 text-sm text-muted-foreground">
                Choose a warehouse to browse and edit its data dictionary.
              </p>
              {(() => {
                const list = filterBySearch(warehouses, warehouseView.query, w => w.name)
                return (
                  <>
                    <ResourceToolbar
                      query={warehouseView.query}
                      onQuery={warehouseView.setQuery}
                      view={warehouseView.view}
                      onView={warehouseView.setView}
                      placeholder="Search warehouses…"
                    />
                    {warehouses.length === 0 ? (
                      <p className="py-10 text-center text-sm text-muted-foreground">
                        No warehouse connections yet. Add one under Admin → Warehouses.
                      </p>
                    ) : list.length === 0 ? (
                      <p className="py-10 text-center text-sm text-muted-foreground">
                        No warehouses match “{warehouseView.query}”.
                      </p>
                    ) : warehouseView.view === 'card' ? (
                      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
                        {list.map(w => (
                          <button
                            key={w.id}
                            type="button"
                            onClick={() => setSelectedWarehouseId(w.id)}
                            className="rounded-xl border border-border bg-card p-4 text-left shadow-sm transition-colors hover:border-primary/50 hover:bg-primary-subtle/30"
                          >
                            <div className="flex items-center gap-2">
                              <Database className="h-4 w-4 shrink-0 text-muted-foreground" />
                              <span className="truncate font-medium text-foreground">{w.name}</span>
                            </div>
                            <p className="mt-2 text-xs text-muted-foreground">
                              {w.schemas.length} schema{w.schemas.length === 1 ? '' : 's'}
                            </p>
                          </button>
                        ))}
                      </div>
                    ) : (
                      <div className="divide-y divide-border rounded-xl border border-border bg-card">
                        {list.map(w => (
                          <button
                            key={w.id}
                            type="button"
                            onClick={() => setSelectedWarehouseId(w.id)}
                            className="flex w-full items-center gap-3 px-4 py-3 text-left transition-colors hover:bg-accent"
                          >
                            <Database className="h-4 w-4 shrink-0 text-muted-foreground" />
                            <span className="flex-1 truncate font-medium text-foreground">{w.name}</span>
                            <span className="text-xs text-muted-foreground">
                              {w.schemas.length} schema{w.schemas.length === 1 ? '' : 's'}
                            </span>
                          </button>
                        ))}
                      </div>
                    )}
                  </>
                )
              })()}
            </div>
          ) : !hasSelection ? (
            <div className="p-4">
              {(() => {
                const tq = tableView.query.toLowerCase()
                const sections = schemas
                  .filter(s => showHidden || !excludedSchemas.has(s.name))
                  .map(s => ({
                    name: s.name,
                    tables: s.tables.filter(
                      t =>
                        (showHidden || !excludedTables.has(`${s.name}.${t.name}`)) &&
                        (!tq ||
                          t.name.toLowerCase().includes(tq) ||
                          s.name.toLowerCase().includes(tq)),
                    ),
                  }))
                  .filter(s => s.tables.length > 0 || (!tq && true))
                return (
                  <>
                    <ResourceToolbar
                      query={tableView.query}
                      onQuery={tableView.setQuery}
                      view={tableView.view}
                      onView={tableView.setView}
                      placeholder="Search tables & views…"
                    />
                    {sections.length === 0 ? (
                      <p className="py-10 text-center text-sm text-muted-foreground">
                        No tables or views. Populate the dictionary from the warehouse first.
                      </p>
                    ) : (
                      <div className="space-y-3">
                        {sections.map(section => {
                          const expanded = !collapsedSchemas.has(section.name) || !!tq
                          return (
                            <div key={section.name} className="rounded-lg border border-border bg-card">
                              <button
                                type="button"
                                onClick={() => toggleBrowserSchema(section.name)}
                                className="flex w-full items-center gap-2 border-b border-border px-3 py-2 text-left"
                              >
                                {expanded ? (
                                  <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
                                ) : (
                                  <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
                                )}
                                <span className="font-mono text-sm font-medium text-foreground">{section.name}</span>
                                <span className="ml-auto text-xs text-muted-foreground">
                                  {section.tables.length} object{section.tables.length === 1 ? '' : 's'}
                                </span>
                              </button>
                              {expanded && section.tables.length > 0 && (
                                <div className="p-3">
                                  {tableView.view === 'card' ? (
                                    <div className="grid grid-cols-1 gap-2 sm:grid-cols-2 lg:grid-cols-3">
                                      {section.tables.map(t => (
                                        <button
                                          key={t.name}
                                          type="button"
                                          onClick={() => selectTable(section.name, t.name)}
                                          className="flex items-center gap-2 rounded-lg border border-border p-3 text-left transition-colors hover:border-primary/50 hover:bg-primary-subtle/30"
                                        >
                                          <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                                          <span className="min-w-0 flex-1 truncate font-mono text-sm text-foreground">
                                            {t.name}
                                          </span>
                                          {t.object_type === 'view' && (
                                            <span className="shrink-0 rounded bg-assistant-subtle px-1.5 py-0.5 text-[10px] font-medium text-assistant">
                                              view
                                            </span>
                                          )}
                                        </button>
                                      ))}
                                    </div>
                                  ) : (
                                    <div className="divide-y divide-border">
                                      {section.tables.map(t => (
                                        <button
                                          key={t.name}
                                          type="button"
                                          onClick={() => selectTable(section.name, t.name)}
                                          className="flex w-full items-center gap-2 px-1 py-2 text-left transition-colors hover:bg-accent"
                                        >
                                          <Table2 className="h-4 w-4 shrink-0 text-muted-foreground" />
                                          <span className="flex-1 truncate font-mono text-sm text-foreground">{t.name}</span>
                                          {t.object_type === 'view' && (
                                            <span className="shrink-0 rounded bg-assistant-subtle px-1.5 py-0.5 text-[10px] font-medium text-assistant">
                                              view
                                            </span>
                                          )}
                                          <ChevronRight className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                                        </button>
                                      ))}
                                    </div>
                                  )}
                                </div>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    )}
                  </>
                )
              })()}
            </div>
          ) : loadingEntries ? (
            <div className="flex h-full items-center justify-center">
              <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
          ) : entries.length === 0 ? (
            <div className="flex h-full flex-col items-center justify-center text-center py-20">
              <p className="text-sm text-muted-foreground">
                No entries yet. Click{' '}
                <span className="font-medium text-muted-foreground">Populate columns</span> to import
                column definitions from the warehouse.
              </p>
            </div>
          ) : (
            <>
              {colQ && (
                <div className="px-5 py-2 bg-warning-subtle border-b border-yellow-100 text-xs text-warning-strong">
                  Showing {filteredEntries.length} of {entries.length} columns matching &ldquo;{columnSearch}&rdquo;
                </div>
              )}
              <table className="min-w-full divide-y divide-border text-sm">
                <thead className="bg-muted sticky top-0 z-10">
                  <tr>
                    {['Column', 'Type', 'Keys', 'Description', 'PII', 'Tags', 'AI', ''].map((h, i) => (
                      <th
                        key={i}
                        scope="col"
                        className="px-4 py-2.5 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                      >
                        {h}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y divide-border bg-card">
                  {filteredEntries.map(entry => (
                    <EntryRow
                      key={entry.id}
                      entry={entry}
                      onSave={handleSaveEntry}
                      onDelete={handleDeleteEntry}
                      onShowHistory={setHistoryEntry}
                      searchQuery={columnSearch}
                      allTables={allTables}
                      warehouseConnectionId={selectedWarehouseId}
                    />
                  ))}
                </tbody>
              </table>
            </>
          )}
        </div>
      </div>

      {/* History modal */}
      {historyEntry && (
        <HistoryModal
          entry={historyEntry}
          onClose={() => setHistoryEntry(null)}
          onRevert={handleRevertEntry}
        />
      )}

      {/* Search dialog */}
      {searchOpen && selectedWarehouseId && (
        <SearchDialog
          warehouseConnectionId={selectedWarehouseId}
          onNavigate={handleNavigateToResult}
          onClose={() => setSearchOpen(false)}
        />
      )}

      {/* Revert modal */}
      {revertOpen && selectedWarehouseId && (
        <RevertModal
          warehouseConnectionId={selectedWarehouseId}
          onClose={() => setRevertOpen(false)}
          onReverted={() => void loadEntries()}
        />
      )}

      {/* Share dialog */}
      {shareOpen && selectedWarehouseId && (
        <ShareResourceDialog
          resourceLabel="Data Dictionary"
          resourceName={warehouses.find(w => w.id === selectedWarehouseId)?.name ?? ''}
          permissionsPath={`/admin/data-dictionary/${selectedWarehouseId}/permissions`}
          apiFetch={apiFetch}
          onClose={() => setShareOpen(false)}
        />
      )}
    </div>
  )
}
