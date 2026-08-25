'use client'

/**
 * Form for creating or editing a dashboard configuration.
 *
 * For Tableau dashboards, an inline workbook → view picker lets admins browse
 * their Tableau site and select a view. Thumbnails are proxied through the
 * FastAPI embed endpoint so Tableau credentials stay server-side.
 */
import type { KeyboardEvent } from 'react';
import { useState, useEffect, useCallback, useRef } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { ChevronDown, ChevronUp, ExternalLink, Plug, Plus, Trash2, X } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { Input, Select, buttonVariants } from '@/components/ui'
import { isShareOnlyUrl, normalizePublicEmbedUrl } from './publicEmbedUrl'

interface DashboardCreatorProps {
  dashboardId?: number
  onSuccess: () => void
  onCancel: () => void
}

interface TableauWorkbook {
  id: string
  name: string
  project_name: string
}

interface TableauView {
  id: string
  name: string
  embed_url: string
  thumbnail_url: string | null
}

interface PowerBIWorkspace {
  id: string
  name: string
}

interface PowerBIReport {
  id: string
  name: string
  embed_url: string
}

type ValueType = 'static' | 'user_attribute'
type UserAttribute = 'email' | 'user_id' | 'role'

interface EmbedFilterRow {
  field: string
  value_type: ValueType
  user_attribute: UserAttribute | ''
  static_value: string
}

interface EmbedParameterRow {
  name: string
  value_type: ValueType
  user_attribute: UserAttribute | ''
  static_value: string
}

interface EmbedConfig {
  filters: EmbedFilterRow[]
  parameters: EmbedParameterRow[]
}

interface PBIEmbedFilterRow {
  table: string
  column: string
  value_type: ValueType
  user_attribute: UserAttribute | ''
  static_value: string
}

interface PBIEmbedConfig {
  filters: PBIEmbedFilterRow[]
}

const EMPTY_EMBED_CONFIG: EmbedConfig = { filters: [], parameters: [] }
const EMPTY_PBI_EMBED_CONFIG: PBIEmbedConfig = { filters: [] }

const USER_ATTRIBUTES: { value: UserAttribute; label: string }[] = [
  { value: 'email', label: 'User email' },
  { value: 'user_id', label: 'User ID' },
  { value: 'role', label: 'User role' },
]

interface BiConnection {
  id: number
  name: string
  provider: string
  provider_label: string
  requires_auth: boolean
}

// Maps a connection's provider to the picker/embedding mode the form drives.
// Public providers (Tableau Public, Looker Studio) embed a public URL directly.
type EmbedMode = 'powerbi' | 'tableau' | 'public'
const PROVIDER_MODE: Record<string, EmbedMode> = {
  powerbi: 'powerbi',
  tableau: 'tableau',
  tableau_public: 'public',
  looker_studio: 'public',
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/**
 * Extract workbook name from a saved view_url.
 * Handles both full URLs (.../views/WorkbookName/ViewName)
 * and bare Tableau contentUrls (WorkbookName/sheets/ViewName).
 */
function extractWorkbookName(viewUrl: string): string {
  const viewsMatch = viewUrl.match(/\/views\/([^/?#]+)/)
  if (viewsMatch) return decodeURIComponent(viewsMatch[1])
  return viewUrl.split('/')[0]
}

/**
 * Extract view name from a saved view_url.
 * Handles both full URLs and bare contentUrls.
 */
function extractViewName(viewUrl: string): string {
  const viewsMatch = viewUrl.match(/\/views\/[^/?#]+\/([^/?#]+)/)
  if (viewsMatch) return decodeURIComponent(viewsMatch[1])
  const parts = viewUrl.split('/')
  return parts[parts.length - 1]
}

/** Renders a Tableau view thumbnail fetched with the session Bearer token. */
function ViewThumbnail({ viewId, token, connectionId }: { viewId: string; token: string; connectionId: number | null }) {
  const [src, setSrc] = useState<string | null>(null)

  useEffect(() => {
    let objectUrl: string | null = null
    const q = connectionId != null ? `?connection_id=${connectionId}` : ''
    fetch(`${API_BASE}/embed/tableau/views/${viewId}/thumbnail${q}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => (r.ok ? r.blob() : null))
      .then(blob => {
        if (!blob) return
        objectUrl = URL.createObjectURL(blob)
        setSrc(objectUrl)
      })
      .catch(() => {})
    return () => {
      if (objectUrl) URL.revokeObjectURL(objectUrl)
    }
  }, [viewId, token, connectionId])

  if (!src) {
    return <div className="h-20 w-full animate-pulse rounded bg-muted" />
  }
  // eslint-disable-next-line @next/next/no-img-element -- src is an object URL from a fetched blob
  return <img src={src} alt="" className="h-20 w-full rounded object-cover" />
}

export function DashboardCreator({ dashboardId, onSuccess, onCancel }: DashboardCreatorProps) {
  const { data: session } = useSession()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  // embedType is the picker/render mode derived from the selected connection.
  const [embedType, setEmbedType] = useState<EmbedMode>('powerbi')
  const [connections, setConnections] = useState<BiConnection[]>([])
  const [biConnectionId, setBiConnectionId] = useState<number | null>(null)
  const [publicUrl, setPublicUrl] = useState('')
  const [tags, setTags] = useState<string[]>([])
  const [tagInput, setTagInput] = useState('')
  const [loading, setLoading] = useState(false)
  // Prevents the form from showing stale defaults while edit data is in-flight
  const [dataLoading, setDataLoading] = useState(!!dashboardId)

  // Tableau-specific state
  const [workbooks, setWorkbooks] = useState<TableauWorkbook[]>([])
  const [selectedWorkbookId, setSelectedWorkbookId] = useState('')
  const [views, setViews] = useState<TableauView[]>([])
  const [selectedViewId, setSelectedViewId] = useState('')
  // Holds the view_id loaded from an existing dashboard config so the views
  // effect can preserve it instead of clearing it when the workbook is set.
  const preserveViewIdRef = useRef<string>('')
  // When view_id wasn't stored (legacy saves), holds the view name extracted from
  // view_url so the views effect can match by name after views load.
  const preserveViewNameRef = useRef<string>('')
  // Stores the raw settings object from the DB so edit mode can fall back to
  // original values when the user hasn't re-selected a view in this session.
  const originalSettingsRef = useRef<Record<string, unknown>>({})
  const [workbooksLoading, setWorkbooksLoading] = useState(false)
  const [viewsLoading, setViewsLoading] = useState(false)
  const [tableauError, setTableauError] = useState<string | null>(null)
  const [embedConfig, setEmbedConfig] = useState<EmbedConfig>(EMPTY_EMBED_CONFIG)
  const [showAdvanced, setShowAdvanced] = useState(false)

  // Power BI-specific state
  const [pbiWorkspaces, setPbiWorkspaces] = useState<PowerBIWorkspace[]>([])
  const [selectedPbiWorkspaceId, setSelectedPbiWorkspaceId] = useState('')
  const [pbiReports, setPbiReports] = useState<PowerBIReport[]>([])
  const [selectedPbiReportId, setSelectedPbiReportId] = useState('')
  const [pbiWorkspacesLoading, setPbiWorkspacesLoading] = useState(false)
  const [pbiReportsLoading, setPbiReportsLoading] = useState(false)
  const [pbiError, setPbiError] = useState<string | null>(null)
  const [pbiEmbedConfig, setPbiEmbedConfig] = useState<PBIEmbedConfig>(EMPTY_PBI_EMBED_CONFIG)
  const [showPbiAdvanced, setShowPbiAdvanced] = useState(false)

  const token = session?.user?.access_token ?? ''
  const apiFetch = createClientFetch(token)

  // Only Power BI / Tableau / public-surface connections can back a dashboard.
  const usableConnections = connections.filter(c => c.provider in PROVIDER_MODE)

  // Only shown when the paste actually needed rewriting — echoing an unchanged
  // URL back at the admin is noise.
  const normalizedPublicUrl =
    publicUrl.trim() && isShareOnlyUrl(publicUrl) ? normalizePublicEmbedUrl(publicUrl) : null
  const connSearchParams = biConnectionId != null ? { connection_id: biConnectionId } : undefined

  // Load the org's BI connections for the connection picker.
  useEffect(() => {
    if (!token) return
    apiFetch<BiConnection[]>('/bi-connections')
      .then(setConnections)
      .catch(() => toast.error('Failed to load BI connections.'))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token])

  // Load existing dashboard data in edit mode
  useEffect(() => {
    if (!dashboardId || !token) return
    apiFetch<Record<string, unknown>>(`/admin/dashboards/${dashboardId}`)
      .then(data => {
        setName(data.name as string)
        setSlug(data.slug as string)
        setDescription((data.description as string) ?? '')
        const rawType = (data.embed_type as string) ?? 'powerbi'
        // Stored embed_type is 'powerbi' | 'tableau' | 'iframe' (public) | legacy.
        const et: EmbedMode = rawType === 'tableau' ? 'tableau' : rawType === 'powerbi' ? 'powerbi' : 'public'
        setEmbedType(et)
        setBiConnectionId((data.bi_connection_id as number | null) ?? null)
        setTags((data.tags as string[]) ?? [])
        const s = (data.settings ?? {}) as Record<string, unknown>
        originalSettingsRef.current = s
        if (et === 'public') {
          setPublicUrl((s.embed_url as string) ?? (s.view_url as string) ?? '')
        }
        if (et === 'tableau') {
          const ec = (s.embed_config ?? EMPTY_EMBED_CONFIG) as EmbedConfig
          setEmbedConfig(ec)
          if (ec.filters.length > 0 || ec.parameters.length > 0) setShowAdvanced(true)
          if (s.workbook_id) setSelectedWorkbookId(s.workbook_id as string)
          if (s.view_id) {
            preserveViewIdRef.current = s.view_id as string
            setSelectedViewId(s.view_id as string)
          }
        } else if (et === 'powerbi') {
          const ec = (s.embed_config ?? EMPTY_PBI_EMBED_CONFIG) as PBIEmbedConfig
          setPbiEmbedConfig(ec)
          if (ec.filters.length > 0) setShowPbiAdvanced(true)
          if (s.workspace_id) setSelectedPbiWorkspaceId(s.workspace_id as string)
          if (s.report_id) setSelectedPbiReportId(s.report_id as string)
        }
      })
      .catch(() => toast.error('Failed to load dashboard'))
      .finally(() => setDataLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboardId, token])

  // Load Tableau workbooks when embed type switches to tableau
  const loadWorkbooks = useCallback(async () => {
    if (!token) return
    setWorkbooksLoading(true)
    setTableauError(null)
    try {
      const data = await apiFetch<TableauWorkbook[]>('/embed/tableau/workbooks',
        connSearchParams ? { searchParams: connSearchParams } : undefined)
      setWorkbooks(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load Tableau workbooks.'
      setTableauError(msg)
    } finally {
      setWorkbooksLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, biConnectionId])

  useEffect(() => {
    if (embedType === 'tableau' && workbooks.length === 0) {
      void loadWorkbooks()
    }
  }, [embedType, workbooks.length, loadWorkbooks])

  // Auto-recover workbook selection for dashboards saved before workbook_id was stored.
  // When workbooks load but selectedWorkbookId is still empty, try to match by name
  // extracted from the saved view_url (format: "WorkbookName/sheets/ViewName" or full URL).
  useEffect(() => {
    if (workbooks.length === 0 || selectedWorkbookId) return
    const viewUrl = originalSettingsRef.current.view_url as string | undefined
    if (!viewUrl || originalSettingsRef.current.workbook_id) return
    const wbName = extractWorkbookName(viewUrl)
    const match = workbooks.find(wb => wb.name === wbName)
    if (match) {
      if (!preserveViewIdRef.current) {
        // No view_id stored either — extract the view name so the views effect
        // can match it by name once views for this workbook load.
        preserveViewNameRef.current = extractViewName(viewUrl)
      }
      setSelectedWorkbookId(match.id)
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [workbooks])

  // Load Power BI workspaces when embed type switches to powerbi
  const loadPbiWorkspaces = useCallback(async () => {
    if (!token) return
    setPbiWorkspacesLoading(true)
    setPbiError(null)
    try {
      const data = await apiFetch<PowerBIWorkspace[]>('/embed/powerbi/workspaces',
        connSearchParams ? { searchParams: connSearchParams } : undefined)
      setPbiWorkspaces(data)
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Failed to load Power BI workspaces.'
      setPbiError(msg)
    } finally {
      setPbiWorkspacesLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, biConnectionId])

  useEffect(() => {
    if (embedType === 'powerbi' && pbiWorkspaces.length === 0) {
      void loadPbiWorkspaces()
    }
  }, [embedType, pbiWorkspaces.length, loadPbiWorkspaces])

  // Load Power BI reports when a workspace is selected
  useEffect(() => {
    if (!selectedPbiWorkspaceId || !token) return
    setPbiReportsLoading(true)
    setPbiReports([])
    apiFetch<PowerBIReport[]>(`/embed/powerbi/workspaces/${selectedPbiWorkspaceId}/reports`,
      connSearchParams ? { searchParams: connSearchParams } : undefined)
      .then(data => setPbiReports(data))
      .catch(() => setPbiError('Failed to load reports for this workspace.'))
      .finally(() => setPbiReportsLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedPbiWorkspaceId, token, biConnectionId])

  // Load views when a workbook is selected
  useEffect(() => {
    if (!selectedWorkbookId || !token) return
    setViewsLoading(true)
    setViews([])
    // When the workbook comes from loading an existing dashboard config,
    // preserveViewIdRef (or preserveViewNameRef for legacy saves) holds the
    // selection — don't clear selectedViewId in that case.
    if (!preserveViewIdRef.current && !preserveViewNameRef.current) {
      setSelectedViewId('')
    }
    apiFetch<TableauView[]>(`/embed/tableau/workbooks/${selectedWorkbookId}/views`,
      connSearchParams ? { searchParams: connSearchParams } : undefined)
      .then(data => {
        setViews(data)
        if (preserveViewIdRef.current) {
          preserveViewIdRef.current = ''
        } else if (preserveViewNameRef.current) {
          // Legacy save: no view_id stored — match the view by name from the URL
          const matched = data.find(v => v.name === preserveViewNameRef.current)
          if (matched) setSelectedViewId(matched.id)
          preserveViewNameRef.current = ''
        }
      })
      .catch(() => setTableauError('Failed to load views for this workbook.'))
      .finally(() => setViewsLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [selectedWorkbookId, token, biConnectionId])

  const handleSave = async () => {
    if (!name.trim()) return
    setLoading(true)
    try {
      const selectedView = views.find(v => v.id === selectedViewId)
      const selectedPbiReport = pbiReports.find(r => r.id === selectedPbiReportId)
      const settings: Record<string, unknown> =
        embedType === 'public'
          ? { embed_url: publicUrl.trim() }
          : embedType === 'tableau' && selectedView
          ? {
              workbook_id: selectedWorkbookId,
              view_id: selectedViewId,
              view_url: selectedView.embed_url,
              embed_config: embedConfig,
            }
          : embedType === 'tableau' && dashboardId
            ? {
                // Edit mode but no new view selected — preserve existing DB settings
                // so metadata (name, role, description) can be updated without wiping
                // the Tableau config that was saved in a previous session.
                ...originalSettingsRef.current,
                embed_config: embedConfig,
              }
            : embedType === 'powerbi' && selectedPbiReport
              ? {
                  workspace_id: selectedPbiWorkspaceId,
                  report_id: selectedPbiReportId,
                  embed_url: selectedPbiReport.embed_url,
                  embed_config: pbiEmbedConfig,
                }
              : embedType === 'powerbi' && dashboardId
                ? {
                    ...originalSettingsRef.current,
                    embed_config: pbiEmbedConfig,
                  }
                : {}

      const body = {
        name: name.trim(),
        slug: slug.trim() || name.trim().toLowerCase().replace(/\s+/g, '-'),
        description: description.trim() || null,
        // embed_type is derived server-side from the connection's provider.
        bi_connection_id: biConnectionId,
        tags,
        settings,
        filters: [],
      }
      if (dashboardId) {
        await apiFetch(`/admin/dashboards/${dashboardId}`, {
          method: 'PUT',
          body: JSON.stringify(body),
        })
      } else {
        await apiFetch('/admin/dashboards', {
          method: 'POST',
          body: JSON.stringify(body),
        })
      }
      toast.success(dashboardId ? 'Dashboard updated' : 'Dashboard created')
      onSuccess()
    } catch {
      toast.error('Failed to save dashboard')
    } finally {
      setLoading(false)
    }
  }

  const canSave =
    !!name.trim() &&
    biConnectionId != null &&
    // Public surfaces just need a URL.
    (embedType !== 'public' || !!publicUrl.trim()) &&
    // Allow save when a view was selected this session OR when edit mode has an
    // existing view_url saved from a previous session (so metadata edits don't
    // require re-selecting a view that was already configured).
    (embedType !== 'tableau' || !!selectedViewId || (!!dashboardId && !!originalSettingsRef.current.view_url)) &&
    // In edit mode, allow save even if workspace list is empty (PBI not configured) —
    // the saved report_id from the DB is still valid.
    (embedType !== 'powerbi' || !!selectedPbiReportId || (!!dashboardId && (pbiWorkspaces.length === 0 || !!originalSettingsRef.current.report_id)))

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-2xl rounded-lg bg-card shadow-xl">
        <div className="p-6 space-y-4 max-h-[90vh] overflow-y-auto">
          <h2 className="text-lg font-semibold">
            {dashboardId ? 'Edit Dashboard' : 'Create Dashboard'}
          </h2>

          {dataLoading && (
            <div className="flex items-center justify-center py-12">
              <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary border-t-transparent" />
              <span className="ml-3 text-sm text-muted-foreground">Loading dashboard…</span>
            </div>
          )}

          {!dataLoading && (<>

          {/* Base fields */}
          <div className="space-y-3">
            <div>
              <label className="block text-sm font-medium mb-1">Dashboard name</label>
              <input
                type="text"
                value={name}
                onChange={e => {
                  setName(e.target.value)
                  setSlug(e.target.value.toLowerCase().replace(/\s+/g, '-'))
                }}
                placeholder="e.g. Revenue Overview"
                className="w-full rounded border px-3 py-2 text-sm"
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Description</label>
              <textarea
                value={description}
                onChange={e => setDescription(e.target.value)}
                placeholder="Optional description..."
                className="w-full rounded border px-3 py-2 text-sm resize-none"
                rows={2}
              />
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Tags</label>
              <div className="flex flex-wrap gap-1.5 rounded border px-3 py-2 min-h-[38px] focus-within:ring-1 focus-within:ring-ring">
                {tags.map(tag => (
                  <span
                    key={tag}
                    className="inline-flex items-center gap-1 rounded-full bg-primary-subtle px-2 py-0.5 text-xs font-medium text-info-strong"
                  >
                    {tag}
                    <button
                      type="button"
                      onClick={() => setTags(prev => prev.filter(t => t !== tag))}
                      className="rounded-full hover:bg-primary-subtle"
                    >
                      <X className="h-3 w-3" />
                    </button>
                  </span>
                ))}
                <input
                  type="text"
                  value={tagInput}
                  onChange={e => setTagInput(e.target.value)}
                  onKeyDown={(e: KeyboardEvent<HTMLInputElement>) => {
                    if ((e.key === 'Enter' || e.key === ',') && tagInput.trim()) {
                      e.preventDefault()
                      const newTag = tagInput.trim().toLowerCase()
                      if (!tags.includes(newTag)) setTags(prev => [...prev, newTag])
                      setTagInput('')
                    } else if (e.key === 'Backspace' && !tagInput && tags.length > 0) {
                      setTags(prev => prev.slice(0, -1))
                    }
                  }}
                  placeholder={tags.length === 0 ? 'Add tags (press Enter)' : ''}
                  className="flex-1 min-w-[120px] text-sm outline-none bg-transparent"
                />
              </div>
            </div>

            <div>
              <label className="block text-sm font-medium mb-1">Connection</label>
              {usableConnections.length === 0 ? (
                <div className="space-y-2 rounded-lg border border-warning-subtle bg-warning-subtle px-3 py-2.5 text-xs text-warning-strong">
                  <p>
                    A dashboard embeds a report from a BI platform, so it needs a connection to
                    authenticate against — and none are configured yet.
                  </p>
                  <p>
                    Add a Power BI, Tableau, Tableau Public, or Looker Studio connection, then come
                    back here.
                  </p>
                  {/* Opens in a new tab so the half-filled form is not lost. */}
                  <a
                    href="/admin/bi-connections"
                    target="_blank"
                    rel="noreferrer"
                    className={buttonVariants({ variant: 'outline', size: 'sm' })}
                  >
                    <Plug aria-hidden />
                    Add a BI connection
                    <ExternalLink aria-hidden />
                  </a>
                </div>
              ) : (
                <Select
                  value={biConnectionId ?? ''}
                  onChange={e => {
                    const id = e.target.value ? Number(e.target.value) : null
                    setBiConnectionId(id)
                    const conn = usableConnections.find(c => c.id === id)
                    const mode = conn ? PROVIDER_MODE[conn.provider] : 'powerbi'
                    setEmbedType(mode)
                    // Reset provider-specific picker state when the connection changes.
                    setWorkbooks([]); setSelectedWorkbookId(''); setSelectedViewId('')
                    setPbiWorkspaces([]); setSelectedPbiWorkspaceId(''); setSelectedPbiReportId('')
                    setPublicUrl('')
                  }}
                >
                  <option value="">Select a connection…</option>
                  {usableConnections.map(c => (
                    <option key={c.id} value={c.id}>
                      {c.name} · {c.provider_label}
                    </option>
                  ))}
                </Select>
              )}
              <p className="mt-1 text-xs text-muted-foreground">
                The connection provides the embedding credentials used to authenticate this dashboard.
              </p>
            </div>
          </div>

          {/* Public embed URL (Tableau Public / Looker Studio) */}
          {biConnectionId != null && embedType === 'public' && (
            <div className="space-y-2 rounded-lg border border-info-subtle bg-info-subtle p-4">
              <label
                htmlFor="public-embed-url"
                className="block text-sm font-medium text-info-strong"
              >
                Public embed URL
              </label>
              <Input
                id="public-embed-url"
                type="url"
                value={publicUrl}
                onChange={e => setPublicUrl(e.target.value)}
                placeholder="https://public.tableau.com/views/… or https://lookerstudio.google.com/embed/…"
              />
              <p className="text-xs text-info-strong">
                Paste the share link straight from Tableau Public or Looker Studio — it is
                converted to an embeddable URL for you. Public surfaces need no credentials.
              </p>
              {/* Show the conversion, so a blank embed is never a mystery. */}
              {normalizedPublicUrl !== null && (
                <div className="space-y-1 rounded border border-border bg-card px-3 py-2">
                  <p className="text-xs font-medium text-muted-foreground">Will embed as</p>
                  <code className="block break-all font-mono text-xs text-foreground">
                    {normalizedPublicUrl}
                  </code>
                </div>
              )}
            </div>
          )}

          {/* Tableau view picker */}
          {embedType === 'tableau' && (
            <div className="rounded-lg border border-primary/30 bg-primary-subtle p-4 space-y-3">
              <p className="text-sm font-medium text-info-strong">Select Tableau view</p>

              {tableauError && (
                <div className="rounded border border-destructive-subtle bg-destructive-subtle px-3 py-2 text-xs text-destructive-strong">
                  {tableauError}{' '}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => void loadWorkbooks()}
                  >
                    Retry
                  </button>
                </div>
              )}

              {/* Existing view hint — shown when edit mode has a saved view_url but no workbook_id */}
              {dashboardId && !selectedWorkbookId && !workbooksLoading && (originalSettingsRef.current.view_url as string) && (
                <div className="rounded border border-warning-subtle bg-warning-subtle px-3 py-2 text-xs text-warning-strong">
                  A Tableau view is configured for this dashboard. Select the same workbook below to
                  confirm it, or choose a different one to update.
                  <p className="mt-1 font-mono break-all opacity-70">
                    {originalSettingsRef.current.view_url as string}
                  </p>
                </div>
              )}

              {/* Workbook dropdown */}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">Workbook</label>
                {workbooksLoading ? (
                  <div className="h-9 w-full animate-pulse rounded bg-secondary" />
                ) : (
                  <Select
                    value={selectedWorkbookId}
                    onChange={e => setSelectedWorkbookId(e.target.value)}
                  >
                    <option value="">Select a workbook…</option>
                    {workbooks.map(wb => (
                      <option key={wb.id} value={wb.id}>
                        {wb.project_name ? `${wb.project_name} / ${wb.name}` : wb.name}
                      </option>
                    ))}
                  </Select>
                )}
              </div>

              {/* View grid with thumbnails */}
              {selectedWorkbookId && (
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-2">View</label>
                  {viewsLoading ? (
                    <div className="grid grid-cols-3 gap-3">
                      {[1, 2, 3].map(i => (
                        <div key={i} className="space-y-1">
                          <div className="h-20 w-full animate-pulse rounded bg-secondary" />
                          <div className="h-3 w-2/3 animate-pulse rounded bg-secondary" />
                        </div>
                      ))}
                    </div>
                  ) : views.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No views found in this workbook.</p>
                  ) : (
                    <div className="grid grid-cols-3 gap-3">
                      {views.map(view => (
                        <button
                          key={view.id}
                          type="button"
                          onClick={() => setSelectedViewId(view.id)}
                          className={`rounded-lg border-2 p-1 text-left transition-colors ${
 selectedViewId === view.id
 ? 'border-primary bg-card'
 : 'border-transparent bg-card hover:border-border-strong'
 }`}
                        >
                          <ViewThumbnail viewId={view.id} token={token} connectionId={biConnectionId} />
                          <p className="mt-1 truncate text-xs font-medium text-foreground">
                            {view.name}
                          </p>
                        </button>
                      ))}
                    </div>
                  )}
                </div>
              )}

              {selectedViewId && (
                <p className="text-xs text-success-strong">
                  ✓ View selected:{' '}
                  <span className="font-medium">
                    {views.find(v => v.id === selectedViewId)?.name}
                  </span>
                </p>
              )}
            </div>
          )}

          {/* Power BI report picker */}
          {embedType === 'powerbi' && (
            <div className="rounded-lg border border-primary/30 bg-primary-subtle p-4 space-y-3">
              <p className="text-sm font-medium text-info-strong">Select Power BI report</p>

              {pbiError && (
                <div className="rounded border border-destructive-subtle bg-destructive-subtle px-3 py-2 text-xs text-destructive-strong">
                  {pbiError}{' '}
                  <button
                    type="button"
                    className="underline"
                    onClick={() => void loadPbiWorkspaces()}
                  >
                    Retry
                  </button>
                </div>
              )}

              {/* Workspace dropdown */}
              <div>
                <label className="block text-xs font-medium text-muted-foreground mb-1">Workspace</label>
                {pbiWorkspacesLoading ? (
                  <div className="h-9 w-full animate-pulse rounded bg-secondary" />
                ) : pbiWorkspaces.length === 0 && !pbiError ? (
                  <div className="rounded border border-warning-subtle bg-warning-subtle px-3 py-2 text-xs text-warning-strong">
                    No workspaces found. Check the service principal credentials on this
                    connection in <strong>Admin → BI Connections</strong>.
                    {selectedPbiWorkspaceId && (
                      <p className="mt-1">Saved workspace ID: <code>{selectedPbiWorkspaceId}</code></p>
                    )}
                  </div>
                ) : (
                  <Select
                    value={selectedPbiWorkspaceId}
                    onChange={e => {
                      setSelectedPbiWorkspaceId(e.target.value)
                      setSelectedPbiReportId('')
                    }}
                  >
                    <option value="">Select a workspace…</option>
                    {pbiWorkspaces.map(ws => (
                      <option key={ws.id} value={ws.id}>
                        {ws.name}
                      </option>
                    ))}
                  </Select>
                )}
              </div>

              {/* Report dropdown */}
              {selectedPbiWorkspaceId && (
                <div>
                  <label className="block text-xs font-medium text-muted-foreground mb-1">Report</label>
                  {pbiReportsLoading ? (
                    <div className="h-9 w-full animate-pulse rounded bg-secondary" />
                  ) : pbiReports.length === 0 ? (
                    <p className="text-xs text-muted-foreground">No reports found in this workspace.</p>
                  ) : (
                    <Select
                      value={selectedPbiReportId}
                      onChange={e => setSelectedPbiReportId(e.target.value)}
                    >
                      <option value="">Select a report…</option>
                      {pbiReports.map(r => (
                        <option key={r.id} value={r.id}>
                          {r.name}
                        </option>
                      ))}
                    </Select>
                  )}
                </div>
              )}

              {selectedPbiReportId && (
                <p className="text-xs text-success-strong">
                  ✓ Report selected:{' '}
                  <span className="font-medium">
                    {pbiReports.find(r => r.id === selectedPbiReportId)?.name}
                  </span>
                </p>
              )}
            </div>
          )}

          {/* Advanced Embed Configuration — Power BI only */}
          {embedType === 'powerbi' && (
            <div className="rounded-lg border border-border bg-muted">
              <button
                type="button"
                onClick={() => setShowPbiAdvanced(v => !v)}
                className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-foreground hover:bg-accent rounded-lg"
              >
                <span>Advanced Embed Configuration</span>
                {showPbiAdvanced ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>

              {showPbiAdvanced && (
                <div className="border-t border-border px-4 pb-4 pt-3 space-y-5">
                  <p className="text-xs text-muted-foreground">
                    Row-level security filters are applied to the report before it renders via
                    the Power BI JS API. Use <strong>User attribute</strong> to automatically
                    populate the value from the logged-in user.
                  </p>

                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold text-foreground uppercase tracking-wide">
                        RLS Filters
                      </p>
                      <button
                        type="button"
                        onClick={() =>
                          setPbiEmbedConfig(c => ({
                            ...c,
                            filters: [
                              ...c.filters,
                              {
                                table: '',
                                column: '',
                                value_type: 'static',
                                user_attribute: '',
                                static_value: '',
                              },
                            ],
                          }))
                        }
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary-subtle"
                      >
                        <Plus className="h-3 w-3" />
                        Add filter
                      </button>
                    </div>

                    {pbiEmbedConfig.filters.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">No RLS filters configured.</p>
                    ) : (
                      <div className="space-y-2">
                        {pbiEmbedConfig.filters.map((row, i) => (
                          <div
                            key={i}
                            className="grid grid-cols-[1fr_1fr_auto_1fr_auto] gap-2 items-center"
                          >
                            <input
                              type="text"
                              value={row.table}
                              onChange={e => {
                                const updated = [...pbiEmbedConfig.filters]
                                updated[i] = { ...updated[i], table: e.target.value }
                                setPbiEmbedConfig(c => ({ ...c, filters: updated }))
                              }}
                              placeholder="Table name"
                              className="rounded border border-border-strong px-2 py-1.5 text-xs"
                            />
                            <input
                              type="text"
                              value={row.column}
                              onChange={e => {
                                const updated = [...pbiEmbedConfig.filters]
                                updated[i] = { ...updated[i], column: e.target.value }
                                setPbiEmbedConfig(c => ({ ...c, filters: updated }))
                              }}
                              placeholder="Column name"
                              className="rounded border border-border-strong px-2 py-1.5 text-xs"
                            />
                            <Select
                              value={row.value_type}
                              onChange={e => {
                                const updated = [...pbiEmbedConfig.filters]
                                updated[i] = {
                                  ...updated[i],
                                  value_type: e.target.value as ValueType,
                                  user_attribute: '',
                                  static_value: '',
                                }
                                setPbiEmbedConfig(c => ({ ...c, filters: updated }))
                              }} size="sm"
                            >
                              <option value="static">Static value</option>
                              <option value="user_attribute">User attribute</option>
                            </Select>
                            {row.value_type === 'user_attribute' ? (
                              <Select
                                value={row.user_attribute}
                                onChange={e => {
                                  const updated = [...pbiEmbedConfig.filters]
                                  updated[i] = {
                                    ...updated[i],
                                    user_attribute: e.target.value as UserAttribute,
                                  }
                                  setPbiEmbedConfig(c => ({ ...c, filters: updated }))
                                }} size="sm"
                              >
                                <option value="">Select attribute…</option>
                                {USER_ATTRIBUTES.map(a => (
                                  <option key={a.value} value={a.value}>
                                    {a.label}
                                  </option>
                                ))}
                              </Select>
                            ) : (
                              <input
                                type="text"
                                value={row.static_value}
                                onChange={e => {
                                  const updated = [...pbiEmbedConfig.filters]
                                  updated[i] = { ...updated[i], static_value: e.target.value }
                                  setPbiEmbedConfig(c => ({ ...c, filters: updated }))
                                }}
                                placeholder="Value"
                                className="rounded border border-border-strong px-2 py-1.5 text-xs"
                              />
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                setPbiEmbedConfig(c => ({
                                  ...c,
                                  filters: c.filters.filter((_, j) => j !== i),
                                }))
                              }
                              className="rounded p-1 text-muted-foreground hover:bg-destructive-subtle hover:text-red-500"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Advanced Embed Configuration — Tableau only */}
          {embedType === 'tableau' && (
            <div className="rounded-lg border border-border bg-muted">
              <button
                type="button"
                onClick={() => setShowAdvanced(v => !v)}
                className="flex w-full items-center justify-between px-4 py-3 text-sm font-medium text-foreground hover:bg-accent rounded-lg"
              >
                <span>Advanced Embed Configuration</span>
                {showAdvanced ? (
                  <ChevronUp className="h-4 w-4 text-muted-foreground" />
                ) : (
                  <ChevronDown className="h-4 w-4 text-muted-foreground" />
                )}
              </button>

              {showAdvanced && (
                <div className="border-t border-border px-4 pb-4 pt-3 space-y-5">
                  <p className="text-xs text-muted-foreground">
                    Filters and parameters are appended to the embed URL when the view loads.
                    Use <strong>User attribute</strong> to automatically populate the value from
                    the logged-in user — useful for row-level security.
                  </p>

                  {/* Embed Filters */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold text-foreground uppercase tracking-wide">
                        Embed Filters
                      </p>
                      <button
                        type="button"
                        onClick={() =>
                          setEmbedConfig(c => ({
                            ...c,
                            filters: [
                              ...c.filters,
                              { field: '', value_type: 'static', user_attribute: '', static_value: '' },
                            ],
                          }))
                        }
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary-subtle"
                      >
                        <Plus className="h-3 w-3" />
                        Add filter
                      </button>
                    </div>

                    {embedConfig.filters.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">No embed filters configured.</p>
                    ) : (
                      <div className="space-y-2">
                        {embedConfig.filters.map((row, i) => (
                          <div key={i} className="grid grid-cols-[1fr_auto_1fr_auto] gap-2 items-center">
                            <input
                              type="text"
                              value={row.field}
                              onChange={e => {
                                const updated = [...embedConfig.filters]
                                updated[i] = { ...updated[i], field: e.target.value }
                                setEmbedConfig(c => ({ ...c, filters: updated }))
                              }}
                              placeholder="Field name"
                              className="rounded border border-border-strong px-2 py-1.5 text-xs"
                            />
                            <Select
                              value={row.value_type}
                              onChange={e => {
                                const updated = [...embedConfig.filters]
                                updated[i] = {
                                  ...updated[i],
                                  value_type: e.target.value as ValueType,
                                  user_attribute: '',
                                  static_value: '',
                                }
                                setEmbedConfig(c => ({ ...c, filters: updated }))
                              }} size="sm"
                            >
                              <option value="static">Static value</option>
                              <option value="user_attribute">User attribute</option>
                            </Select>
                            {row.value_type === 'user_attribute' ? (
                              <Select
                                value={row.user_attribute}
                                onChange={e => {
                                  const updated = [...embedConfig.filters]
                                  updated[i] = {
                                    ...updated[i],
                                    user_attribute: e.target.value as UserAttribute,
                                  }
                                  setEmbedConfig(c => ({ ...c, filters: updated }))
                                }} size="sm"
                              >
                                <option value="">Select attribute…</option>
                                {USER_ATTRIBUTES.map(a => (
                                  <option key={a.value} value={a.value}>
                                    {a.label}
                                  </option>
                                ))}
                              </Select>
                            ) : (
                              <input
                                type="text"
                                value={row.static_value}
                                onChange={e => {
                                  const updated = [...embedConfig.filters]
                                  updated[i] = { ...updated[i], static_value: e.target.value }
                                  setEmbedConfig(c => ({ ...c, filters: updated }))
                                }}
                                placeholder="Value"
                                className="rounded border border-border-strong px-2 py-1.5 text-xs"
                              />
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                setEmbedConfig(c => ({
                                  ...c,
                                  filters: c.filters.filter((_, j) => j !== i),
                                }))
                              }
                              className="rounded p-1 text-muted-foreground hover:bg-destructive-subtle hover:text-red-500"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>

                  {/* Embed Parameters */}
                  <div className="space-y-2">
                    <div className="flex items-center justify-between">
                      <p className="text-xs font-semibold text-foreground uppercase tracking-wide">
                        Embed Parameters
                      </p>
                      <button
                        type="button"
                        onClick={() =>
                          setEmbedConfig(c => ({
                            ...c,
                            parameters: [
                              ...c.parameters,
                              { name: '', value_type: 'static', user_attribute: '', static_value: '' },
                            ],
                          }))
                        }
                        className="inline-flex items-center gap-1 rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary-subtle"
                      >
                        <Plus className="h-3 w-3" />
                        Add parameter
                      </button>
                    </div>

                    {embedConfig.parameters.length === 0 ? (
                      <p className="text-xs text-muted-foreground italic">No embed parameters configured.</p>
                    ) : (
                      <div className="space-y-2">
                        {embedConfig.parameters.map((row, i) => (
                          <div key={i} className="grid grid-cols-[1fr_auto_1fr_auto] gap-2 items-center">
                            <input
                              type="text"
                              value={row.name}
                              onChange={e => {
                                const updated = [...embedConfig.parameters]
                                updated[i] = { ...updated[i], name: e.target.value }
                                setEmbedConfig(c => ({ ...c, parameters: updated }))
                              }}
                              placeholder="Parameter name"
                              className="rounded border border-border-strong px-2 py-1.5 text-xs"
                            />
                            <Select
                              value={row.value_type}
                              onChange={e => {
                                const updated = [...embedConfig.parameters]
                                updated[i] = {
                                  ...updated[i],
                                  value_type: e.target.value as ValueType,
                                  user_attribute: '',
                                  static_value: '',
                                }
                                setEmbedConfig(c => ({ ...c, parameters: updated }))
                              }} size="sm"
                            >
                              <option value="static">Static value</option>
                              <option value="user_attribute">User attribute</option>
                            </Select>
                            {row.value_type === 'user_attribute' ? (
                              <Select
                                value={row.user_attribute}
                                onChange={e => {
                                  const updated = [...embedConfig.parameters]
                                  updated[i] = {
                                    ...updated[i],
                                    user_attribute: e.target.value as UserAttribute,
                                  }
                                  setEmbedConfig(c => ({ ...c, parameters: updated }))
                                }} size="sm"
                              >
                                <option value="">Select attribute…</option>
                                {USER_ATTRIBUTES.map(a => (
                                  <option key={a.value} value={a.value}>
                                    {a.label}
                                  </option>
                                ))}
                              </Select>
                            ) : (
                              <input
                                type="text"
                                value={row.static_value}
                                onChange={e => {
                                  const updated = [...embedConfig.parameters]
                                  updated[i] = { ...updated[i], static_value: e.target.value }
                                  setEmbedConfig(c => ({ ...c, parameters: updated }))
                                }}
                                placeholder="Value"
                                className="rounded border border-border-strong px-2 py-1.5 text-xs"
                              />
                            )}
                            <button
                              type="button"
                              onClick={() =>
                                setEmbedConfig(c => ({
                                  ...c,
                                  parameters: c.parameters.filter((_, j) => j !== i),
                                }))
                              }
                              className="rounded p-1 text-muted-foreground hover:bg-destructive-subtle hover:text-red-500"
                            >
                              <Trash2 className="h-3.5 w-3.5" />
                            </button>
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* Footer buttons */}
          <div className="flex justify-end gap-2 pt-2">
            <button
              onClick={onCancel}
              className="rounded border px-4 py-2 text-sm hover:bg-accent"
            >
              Cancel
            </button>
            <button
              onClick={handleSave}
              disabled={loading || !canSave}
              className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
            >
              {loading
                ? 'Saving...'
                : dashboardId
                  ? 'Update Dashboard'
                  : 'Create Dashboard'}
            </button>
          </div>
          </>)}

        </div>
      </div>
    </div>
  )
}
