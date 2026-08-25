'use client'

/**
 * Individual data dictionary browser.
 *
 * Shows a searchable tree of one warehouse's tables and their column
 * descriptions, sourced from the data dictionary maintained by admins and
 * AI enrichment. Reached by selecting a dictionary from /data-dicts. Access is
 * enforced server-side: the entries endpoint only returns rows for connections
 * shared with the user (or all, for data_dictionary.manage).
 */
import { useState, useEffect, useMemo } from 'react'
import { useParams } from 'next/navigation'
import Link from 'next/link'
import { useSession } from 'next-auth/react'
import { BookOpen, ChevronRight, ChevronDown, Search, Database, ArrowLeft } from 'lucide-react'
import { createClientFetch } from '@/lib/api'

interface DictWarehouse {
  id: number
  name: string
}

interface DictEntry {
  id: number
  schema_name: string
  table_name: string
  column_name: string | null
  description: string | null
  data_type: string | null
  is_pk: boolean
  fk_table: string | null
}

interface TableGroup {
  schema: string
  table: string
  description: string | null
  columns: DictEntry[]
}

function groupEntries(entries: DictEntry[]): TableGroup[] {
  const map = new Map<string, TableGroup>()
  for (const entry of entries) {
    const key = `${entry.schema_name}.${entry.table_name}`
    if (!map.has(key)) {
      map.set(key, {
        schema: entry.schema_name,
        table: entry.table_name,
        description: entry.column_name === null ? (entry.description ?? null) : null,
        columns: [],
      })
    }
    if (entry.column_name !== null) {
      map.get(key)!.columns.push(entry)
    } else if (entry.description) {
      map.get(key)!.description = entry.description
    }
  }
  return Array.from(map.values()).sort((a, b) =>
    `${a.schema}.${a.table}`.localeCompare(`${b.schema}.${b.table}`),
  )
}

function TableRow({ group, query }: { group: TableGroup; query: string }) {
  const [open, setOpen] = useState(false)
  const visibleColumns = query
    ? group.columns.filter(
        c =>
          c.column_name?.toLowerCase().includes(query) ||
          c.description?.toLowerCase().includes(query),
      )
    : group.columns

  const show = !query || group.table.toLowerCase().includes(query) || visibleColumns.length > 0

  if (!show) return null
  const expanded = open || (query.length > 0 && visibleColumns.length > 0)

  return (
    <div className="border border-border rounded-lg overflow-hidden">
      <button
        type="button"
        onClick={() => setOpen(v => !v)}
        className="w-full flex items-center gap-3 px-4 py-3 bg-card hover:bg-accent transition-colors text-left"
      >
        {expanded ? (
          <ChevronDown className="h-4 w-4 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="h-4 w-4 shrink-0 text-muted-foreground" />
        )}
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <span className="text-xs text-muted-foreground font-mono">{group.schema}.</span>
            <span className="font-medium text-foreground font-mono">{group.table}</span>
          </div>
          {group.description && (
            <p className="text-xs text-muted-foreground mt-0.5 truncate">{group.description}</p>
          )}
        </div>
        <span className="shrink-0 text-xs text-muted-foreground ">
          {group.columns.length} col{group.columns.length === 1 ? '' : 's'}
        </span>
      </button>

      {expanded && visibleColumns.length > 0 && (
        <div className="border-t border-border ">
          <table className="min-w-full text-sm">
            <thead className="bg-muted ">
              <tr>
                {['Column', 'Type', 'Description'].map(h => (
                  <th key={h} className="px-4 py-2 text-left text-xs font-semibold text-muted-foreground uppercase tracking-wider">
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody className="divide-y divide-border ">
              {visibleColumns.map(col => (
                <tr key={col.id} className="bg-card ">
                  <td className="px-4 py-2 font-mono text-xs text-foreground whitespace-nowrap">
                    {col.is_pk && (
                      <span className="mr-1 text-amber-500 text-xs" title="Primary key">🔑</span>
                    )}
                    {col.fk_table && (
                      <span className="mr-1 text-primary text-xs" title={`Foreign key → ${col.fk_table}`}>🔗</span>
                    )}
                    {col.column_name}
                  </td>
                  <td className="px-4 py-2 font-mono text-xs text-muted-foreground whitespace-nowrap">
                    {col.data_type ?? '—'}
                  </td>
                  <td className="px-4 py-2 text-xs text-muted-foreground ">
                    {col.description ?? <span className="text-muted-foreground italic">No description</span>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

export default function DataDictDetailPage() {
  const { data: session } = useSession()
  const params = useParams<{ id: string }>()
  const warehouseId = Number(params.id)

  const [name, setName] = useState<string | null>(null)
  const [entries, setEntries] = useState<DictEntry[]>([])
  const [loading, setLoading] = useState(true)
  const [notFound, setNotFound] = useState(false)
  const [query, setQuery] = useState('')

  const apiFetch = createClientFetch(session?.user?.access_token)

  useEffect(() => {
    if (!session?.user?.access_token || Number.isNaN(warehouseId)) return
    setLoading(true)
    void (async () => {
      try {
        const [warehouses, entryData] = await Promise.all([
          apiFetch<DictWarehouse[]>('/data-dictionary/warehouses').catch(() => [] as DictWarehouse[]),
          apiFetch<DictEntry[]>('/data-dictionary', {
            searchParams: { warehouse_connection_id: warehouseId },
          }).catch(() => [] as DictEntry[]),
        ])
        const match = warehouses.find(w => w.id === warehouseId)
        // Access is server-enforced: no accessible warehouse match means the
        // dictionary is not shared with this user.
        if (!match) {
          setNotFound(true)
          return
        }
        setName(match.name)
        setEntries(entryData)
      } finally {
        setLoading(false)
      }
    })()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token, warehouseId])

  const groups = useMemo(() => groupEntries(entries), [entries])
  const q = query.toLowerCase().trim()

  if (loading) {
    return <div className="flex h-64 items-center justify-center text-sm text-muted-foreground ">Loading…</div>
  }

  if (notFound) {
    return (
      <div className="space-y-6">
        <Link href="/data-dicts" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground ">
          <ArrowLeft className="h-4 w-4" />
          Back to Data Dictionaries
        </Link>
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-card py-16 text-center">
          <BookOpen className="mb-3 h-10 w-10 text-muted-foreground " />
          <p className="text-sm font-medium text-foreground ">Data dictionary not available</p>
          <p className="mt-1 text-sm text-muted-foreground ">
            It may not be shared with your role.
          </p>
        </div>
      </div>
    )
  }

  return (
    <div className="space-y-6">
      <div>
        <Link href="/data-dicts" className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground ">
          <ArrowLeft className="h-4 w-4" />
          Back to Data Dictionaries
        </Link>
        <h1 className="mt-2 text-2xl font-semibold text-foreground ">{name}</h1>
        <p className="mt-1 text-sm text-muted-foreground ">
          Browse table and column descriptions for this warehouse.
        </p>
      </div>

      <div className="relative max-w-md">
        <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <input
          type="search"
          value={query}
          onChange={e => setQuery(e.target.value)}
          placeholder="Search tables or columns…"
          className="w-full rounded-lg border border-border-strong bg-card pl-9 pr-3 py-2 text-sm text-foreground placeholder:text-muted-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      {groups.length === 0 ? (
        <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-card py-16 text-center">
          <BookOpen className="mb-3 h-10 w-10 text-muted-foreground " />
          <p className="text-sm font-medium text-foreground ">No data dictionary entries yet</p>
          <p className="mt-1 text-sm text-muted-foreground ">
            Ask your admin to populate the data dictionary.
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {groups.map(group => (
            <TableRow
              key={`${group.schema}.${group.table}`}
              group={group}
              query={q}
            />
          ))}
          {q && groups.every(g => {
            const cols = g.columns.filter(c => c.column_name?.toLowerCase().includes(q) || c.description?.toLowerCase().includes(q))
            return !g.table.toLowerCase().includes(q) && cols.length === 0
          }) && (
            <div className="flex items-center justify-center py-8 text-sm text-muted-foreground ">
              <Database className="mr-2 h-4 w-4" />
              No tables or columns match &ldquo;{query}&rdquo;
            </div>
          )}
        </div>
      )}
    </div>
  )
}
