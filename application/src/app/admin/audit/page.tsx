'use client'

/**
 * Audit log page.
 *
 * Shows a filterable, paginated record of user actions. Filters update the
 * URL search params so bookmarks and browser history work correctly.
 */

import { Suspense, useState, useEffect, useCallback } from 'react'
import { useRouter, useSearchParams, usePathname } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { createClientFetch } from '@/lib/api'
import { LoadingRows } from '@/components/ui/Feedback'
import { Select } from '@/components/ui'

interface AuditEntry {
  id: number
  action: string
  resource_type: string | null
  resource_id: number | null
  resource_name: string | null
  user_email: string | null
  user_name: string | null
  ip_address: string | null
  created_at: string
}

interface AuditResponse {
  entries: AuditEntry[]
  total: number
  page: number
  page_size: number
  total_pages: number
}

const ACTION_PREFIXES = [
  { value: '', label: 'All actions' },
  { value: 'user', label: 'User (login, etc.)' },
  { value: 'dashboard', label: 'Dashboard views' },
  { value: 'page', label: 'Page views' },
  { value: 'data', label: 'Data queries' },
  { value: 'export', label: 'Exports' },
]

function ActionBadge({ action }: { action: string }) {
  const prefix = action.split('.')[0]
  const colors: Record<string, string> = {
    user: 'bg-assistant-subtle text-assistant',
    dashboard: 'bg-primary-subtle text-info-strong',
    page: 'bg-warning-subtle text-warning-strong',
    data: 'bg-success-subtle text-success-strong',
    export: 'bg-orange-50 text-orange-700',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colors[prefix] ?? 'bg-muted text-muted-foreground'}`}
    >
      {action}
    </span>
  )
}

function formatRelative(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  return `${days}d ago`
}

function AuditLogContent() {
  const { data: session } = useSession()
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()

  const page = Math.max(1, parseInt(searchParams.get('page') ?? '1', 10))
  const [actionFilter, setActionFilter] = useState(searchParams.get('action') ?? '')
  const [userFilter, setUserFilter] = useState(searchParams.get('user') ?? '')
  const [fromDate, setFromDate] = useState(searchParams.get('from') ?? '')
  const [toDate, setToDate] = useState(searchParams.get('to') ?? '')

  const [data, setData] = useState<AuditResponse>({
    entries: [],
    total: 0,
    page: 1,
    page_size: 50,
    total_pages: 1,
  })
  const [loading, setLoading] = useState(true)

  const apiFetch = createClientFetch(session?.user?.access_token)

  const load = useCallback(async () => {
    if (!session?.user?.access_token) return
    setLoading(true)
    try {
      const params = new URLSearchParams({ page: String(page), page_size: '50' })
      if (actionFilter) params.set('action', actionFilter)
      if (userFilter) params.set('user_email', userFilter)
      if (fromDate) params.set('from_date', fromDate)
      if (toDate) params.set('to_date', toDate)
      const result = await apiFetch<AuditResponse>(`/audit?${params}`)
      setData(result)
    } catch (err) {
      // The message matters: this page spent a long time failing with a bare
      // "Failed to load audit log." because it was requesting a path that does
      // not exist here, and the 404 was swallowed by this handler.
      toast.error(err instanceof Error ? err.message : 'Failed to load audit log.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token, page, actionFilter, userFilter, fromDate, toDate])

  useEffect(() => {
    void load()
  }, [load])

  function pushFilters(overrides: Record<string, string> = {}) {
    const p = new URLSearchParams()
    p.set('page', '1')
    const a = overrides.action ?? actionFilter
    const u = overrides.user ?? userFilter
    const f = overrides.from ?? fromDate
    const t = overrides.to ?? toDate
    if (a) p.set('action', a)
    if (u) p.set('user', u)
    if (f) p.set('from', f)
    if (t) p.set('to', t)
    router.push(`${pathname}?${p.toString()}`)
  }

  function clearFilters() {
    setActionFilter('')
    setUserFilter('')
    setFromDate('')
    setToDate('')
    router.push(pathname)
  }

  const hasFilters = actionFilter || userFilter || fromDate || toDate

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">Audit Log</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Record of user actions on platform resources.{' '}
          {data.total > 0 && `${data.total.toLocaleString()} entries total.`}
        </p>
      </div>

      {/* Filters */}
      <div className="mb-4 rounded-xl border border-border bg-card p-4 shadow-sm">
        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              Action type
            </label>
            <Select
              value={actionFilter}
              onChange={e => {
                setActionFilter(e.target.value)
                pushFilters({ action: e.target.value })
              }}
            >
              {ACTION_PREFIXES.map(a => (
                <option key={a.value} value={a.value}>
                  {a.label}
                </option>
              ))}
            </Select>
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              User email
            </label>
            <input
              type="text"
              value={userFilter}
              onChange={e => setUserFilter(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && pushFilters({ user: userFilter })}
              onBlur={() => pushFilters({ user: userFilter })}
              placeholder="Filter by email…"
              className="w-full rounded-lg border border-border px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">
              From date
            </label>
            <input
              type="date"
              value={fromDate}
              onChange={e => {
                setFromDate(e.target.value)
                pushFilters({ from: e.target.value })
              }}
              className="w-full rounded-lg border border-border px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>

          <div>
            <label className="block text-xs font-medium text-muted-foreground mb-1">To date</label>
            <input
              type="date"
              value={toDate}
              onChange={e => {
                setToDate(e.target.value)
                pushFilters({ to: e.target.value })
              }}
              className="w-full rounded-lg border border-border px-3 py-1.5 text-sm focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring"
            />
          </div>
        </div>

        {hasFilters && (
          <div className="mt-3 flex items-center gap-2">
            <span className="text-xs text-muted-foreground">Filters active</span>
            <button
              type="button"
              onClick={clearFilters}
              className="text-xs text-primary hover:text-primary"
            >
              Clear all
            </button>
          </div>
        )}
      </div>

      {loading ? (
        <div className="py-12 text-center text-sm text-muted-foreground">Loading…</div>
      ) : data.entries.length === 0 ? (
        <div className="rounded-xl border border-dashed border-border-strong bg-card p-12 text-center">
          <p className="text-sm text-muted-foreground">No audit log entries match these filters.</p>
        </div>
      ) : (
        <>
          <div className="rounded-xl border border-border bg-card overflow-hidden">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-border bg-muted text-xs font-medium text-muted-foreground uppercase tracking-wider">
                  <th className="px-4 py-3 text-left">Action</th>
                  <th className="px-4 py-3 text-left">Resource</th>
                  <th className="px-4 py-3 text-left">User</th>
                  <th className="px-4 py-3 text-left">IP</th>
                  <th className="px-4 py-3 text-left">When</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {data.entries.map(entry => (
                  <tr key={entry.id} className="hover:bg-accent">
                    <td className="px-4 py-3">
                      <ActionBadge action={entry.action} />
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {entry.resource_name ? (
                        <span>
                          {entry.resource_type && (
                            <span className="text-muted-foreground">{entry.resource_type} / </span>
                          )}
                          {entry.resource_name}
                        </span>
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-foreground">
                      {entry.user_name ?? entry.user_email ?? (
                        <span className="text-muted-foreground">System</span>
                      )}
                    </td>
                    <td className="px-4 py-3 text-muted-foreground font-mono text-xs">
                      {entry.ip_address ?? '—'}
                    </td>
                    <td
                      className="px-4 py-3 text-muted-foreground whitespace-nowrap"
                      title={entry.created_at}
                    >
                      {formatRelative(entry.created_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {data.total_pages > 1 && (
            <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
              <span>
                Page {data.page} of {data.total_pages}
              </span>
              <div className="flex gap-2">
                {data.page > 1 && (
                  <a
                    href={`?page=${data.page - 1}${hasFilters ? `&action=${actionFilter}&user=${userFilter}&from=${fromDate}&to=${toDate}` : ''}`}
                    className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-accent"
                  >
                    Previous
                  </a>
                )}
                {data.page < data.total_pages && (
                  <a
                    href={`?page=${data.page + 1}${hasFilters ? `&action=${actionFilter}&user=${userFilter}&from=${fromDate}&to=${toDate}` : ''}`}
                    className="rounded-lg border border-border px-3 py-1.5 text-sm hover:bg-accent"
                  >
                    Next
                  </a>
                )}
              </div>
            </div>
          )}
        </>
      )}
    </div>
  )
}

/**
 * useSearchParams() opts a route out of static prerendering unless it sits
 * inside a Suspense boundary, which fails `next build`.
 */
export default function AuditLogPage() {
  return (
    <Suspense fallback={<LoadingRows rows={8} />}>
      <AuditLogContent />
    </Suspense>
  )
}
