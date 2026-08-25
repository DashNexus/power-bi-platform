'use client'

/**
 * Dashboard management admin page.
 *
 * Lists all dashboard configurations for the organisation with create, edit,
 * permission management, and deactivate/reactivate actions.
 */
import { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { Plus, Settings2, Users, EyeOff, Eye, Layers, Trash2, History } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { DashboardCreator } from '@/components/dashboards/DashboardCreator'
import { ShareResourceDialog } from '@/components/admin/ShareResourceDialog'

interface Dashboard {
  id: number
  name: string
  description: string | null
  slug: string
  embed_type: string
  settings: Record<string, unknown>
  required_role: string
  is_active: boolean
  tags: string[]
}

const TYPE_BADGE: Record<string, string> = {
  powerbi: 'bg-warning-subtle text-warning-strong',
  tableau: 'bg-primary-subtle text-info-strong',
  custom_react: 'bg-purple-100 text-purple-800',
  streamlit: 'bg-success-subtle text-success-strong',
  iframe: 'bg-sky-100 text-sky-800',
}

const TYPE_LABEL: Record<string, string> = {
  powerbi: 'Power BI',
  tableau: 'Tableau',
  custom_react: 'Custom React',
  streamlit: 'Streamlit',
  iframe: 'Public embed',
}

// ---------- Version History Dialog ----------

interface DashboardVersion {
  id: number
  dashboard_id: number
  name: string
  description: string | null
  embed_type: string
  created_by_user_id: number | null
  created_at: string
}

interface VersionHistoryDialogProps {
  dashboard: Dashboard
  onClose: () => void
  onRestored: () => void
  apiFetch: ReturnType<typeof createClientFetch>
}

function VersionHistoryDialog({ dashboard, onClose, onRestored, apiFetch }: VersionHistoryDialogProps) {
  const [versions, setVersions] = useState<DashboardVersion[]>([])
  const [loading, setLoading] = useState(true)
  const [restoringId, setRestoringId] = useState<number | null>(null)

  useEffect(() => {
    apiFetch<DashboardVersion[]>(`/admin/dashboards/${dashboard.id}/versions`)
      .then(setVersions)
      .catch(() => toast.error('Failed to load version history.'))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dashboard.id])

  async function handleRestore(versionId: number) {
    if (!confirm('Restore this version? The current configuration will be saved as a new version first.')) return
    setRestoringId(versionId)
    try {
      await apiFetch(`/admin/dashboards/${dashboard.id}/versions/${versionId}/restore`, { method: 'POST' })
      toast.success('Dashboard restored to selected version.')
      onRestored()
      onClose()
    } catch {
      toast.error('Failed to restore version.')
      setRestoringId(null)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-card p-6 shadow-xl">
        <div className="flex items-start justify-between mb-4">
          <div>
            <h3 className="text-base font-semibold text-foreground">Version History</h3>
            <p className="text-sm text-muted-foreground mt-0.5">{dashboard.name}</p>
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            ✕
          </button>
        </div>

        {loading ? (
          <p className="py-8 text-center text-sm text-muted-foreground">Loading…</p>
        ) : versions.length === 0 ? (
          <p className="py-8 text-center text-sm text-muted-foreground">
            No version history yet. Versions are saved automatically when you edit a dashboard.
          </p>
        ) : (
          <div className="space-y-2 max-h-80 overflow-y-auto">
            {versions.map((v, index) => (
              <div key={v.id} className="flex items-start justify-between rounded-lg border border-border p-3">
                <div>
                  <p className="text-sm font-medium text-foreground">
                    {index === 0 ? 'Latest snapshot' : `Version ${versions.length - index}`}
                  </p>
                  <p className="text-xs text-muted-foreground mt-0.5">
                    {v.name} · {v.embed_type}
                  </p>
                  <p className="text-xs text-muted-foreground">
                    {new Date(v.created_at).toLocaleString('en-US', {
                      month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
                    })}
                  </p>
                </div>
                <button
                  type="button"
                  disabled={restoringId === v.id}
                  onClick={() => void handleRestore(v.id)}
                  className="ml-3 shrink-0 rounded border border-border-strong px-3 py-1 text-xs font-medium text-muted-foreground hover:bg-accent disabled:opacity-50"
                >
                  {restoringId === v.id ? '…' : 'Restore'}
                </button>
              </div>
            ))}
          </div>
        )}

        <div className="mt-4 flex justify-end">
          <button
            onClick={onClose}
            className="rounded border px-4 py-2 text-sm hover:bg-accent"
          >
            Close
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------- Main page ----------

export default function DashboardsAdminPage() {
  const { data: session } = useSession()
  const [dashboards, setDashboards] = useState<Dashboard[]>([])
  const [loading, setLoading] = useState(true)
  const [showCreator, setShowCreator] = useState(false)
  const [editingId, setEditingId] = useState<number | null>(null)
  const [permsDashboard, setPermsDashboard] = useState<Dashboard | null>(null)
  const [historyDashboard, setHistoryDashboard] = useState<Dashboard | null>(null)
  const [deleteConfirmId, setDeleteConfirmId] = useState<number | null>(null)

  const apiFetch = createClientFetch(session?.user?.access_token)

  const loadDashboards = useCallback(async () => {
    if (!session?.user?.access_token) return
    try {
      const data = await apiFetch<Dashboard[]>('/admin/dashboards')
      setDashboards(data)
    } catch {
      toast.error('Failed to load dashboards.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  useEffect(() => {
    void loadDashboards()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  async function handleDelete(id: number) {
    try {
      await apiFetch(`/admin/dashboards/${id}`, { method: 'DELETE' })
      setDashboards(prev => prev.filter(d => d.id !== id))
      toast.success('Dashboard deleted.')
    } catch {
      toast.error('Failed to delete dashboard.')
    } finally {
      setDeleteConfirmId(null)
    }
  }

  async function handleToggleActive(dashboard: Dashboard) {
    try {
      await apiFetch(`/admin/dashboards/${dashboard.id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_active: !dashboard.is_active }),
      })
      setDashboards(prev =>
        prev.map(d =>
          d.id === dashboard.id ? { ...d, is_active: !d.is_active } : d,
        ),
      )
      toast.success(
        `${dashboard.name} ${dashboard.is_active ? 'deactivated' : 'activated'}.`,
      )
    } catch {
      toast.error('Failed to update dashboard.')
    }
  }

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Loading dashboards…
      </div>
    )
  }

  return (
    <>
      {(showCreator || editingId !== null) && (
        <DashboardCreator
          dashboardId={editingId ?? undefined}
          onSuccess={() => {
            setShowCreator(false)
            setEditingId(null)
            void loadDashboards()
          }}
          onCancel={() => {
            setShowCreator(false)
            setEditingId(null)
          }}
        />
      )}

      {permsDashboard && (
        <ShareResourceDialog
          resourceLabel="Dashboard"
          resourceName={permsDashboard.name}
          permissionsPath={`/admin/dashboards/${permsDashboard.id}/permissions`}
          apiFetch={apiFetch}
          onClose={() => setPermsDashboard(null)}
        />
      )}

      {historyDashboard && (
        <VersionHistoryDialog
          dashboard={historyDashboard}
          onClose={() => setHistoryDashboard(null)}
          onRestored={() => void loadDashboards()}
          apiFetch={apiFetch}
        />
      )}

      {deleteConfirmId !== null && (() => {
        const target = dashboards.find(d => d.id === deleteConfirmId)
        return (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="w-full max-w-sm rounded-lg bg-card p-6 shadow-xl space-y-4">
              <h3 className="text-base font-semibold text-foreground">Delete Dashboard</h3>
              <p className="text-sm text-muted-foreground">
                Are you sure you want to delete{' '}
                <span className="font-medium text-foreground">{target?.name}</span>? This action
                cannot be undone.
              </p>
              <div className="flex justify-end gap-2 pt-2">
                <button
                  onClick={() => setDeleteConfirmId(null)}
                  className="rounded border px-4 py-2 text-sm hover:bg-accent"
                >
                  Cancel
                </button>
                <button
                  onClick={() => void handleDelete(deleteConfirmId)}
                  className="rounded bg-destructive px-4 py-2 text-sm font-medium text-white hover:bg-destructive/90"
                >
                  Delete Dashboard
                </button>
              </div>
            </div>
          </div>
        )
      })()}

      <div>
        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Dashboards</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Configure embed sources and manage access for each dashboard.
            </p>
          </div>
          <button
            onClick={() => setShowCreator(true)}
            className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
          >
            <Plus className="h-4 w-4" />
            Create Dashboard
          </button>
        </div>

        {/* Table */}
        {dashboards.length === 0 ? (
          <div className="flex flex-col items-center justify-center rounded-xl border border-dashed border-border-strong bg-card py-20 text-center">
            <Layers className="mb-3 h-10 w-10 text-muted-foreground" />
            <p className="text-sm font-medium text-foreground">No dashboards configured yet.</p>
            <p className="mt-1 text-sm text-muted-foreground">
              Create a dashboard to embed Power BI, Tableau, Streamlit, or a custom React view.
            </p>
            <button
              onClick={() => setShowCreator(true)}
              className="mt-4 inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
            >
              <Plus className="h-4 w-4" />
              Create Dashboard
            </button>
          </div>
        ) : (
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-border text-sm">
                <thead className="bg-muted">
                  <tr>
                    {['Name', 'Type', 'Slug', 'Status', 'Actions'].map(h => (
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
                  {dashboards.map(d => (
                    <tr key={d.id} className="transition-colors hover:bg-accent">
                      <td className="px-4 py-3">
                        <p className="font-medium text-foreground">{d.name}</p>
                        {d.description && (
                          <p className="text-xs text-muted-foreground truncate max-w-xs">
                            {d.description}
                          </p>
                        )}
                        {d.tags && d.tags.length > 0 && (
                          <div className="mt-1 flex flex-wrap gap-1">
                            {d.tags.map(tag => (
                              <span
                                key={tag}
                                className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                              >
                                {tag}
                              </span>
                            ))}
                          </div>
                        )}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${TYPE_BADGE[d.embed_type] ?? 'bg-muted text-muted-foreground'}`}
                        >
                          {TYPE_LABEL[d.embed_type] ?? d.embed_type}
                        </span>
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-muted-foreground">
                        /{d.slug}
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${
 d.is_active
 ? 'bg-success-subtle text-success-strong'
 : 'bg-muted text-muted-foreground'
 }`}
                        >
                          {d.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1">
                          <button
                            onClick={() => setEditingId(d.id)}
                            title="Edit dashboard"
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          >
                            <Settings2 className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => setPermsDashboard(d)}
                            title="Manage access"
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          >
                            <Users className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => setHistoryDashboard(d)}
                            title="Version history"
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          >
                            <History className="h-4 w-4" />
                          </button>
                          <button
                            onClick={() => void handleToggleActive(d)}
                            title={d.is_active ? 'Deactivate' : 'Activate'}
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                          >
                            {d.is_active ? (
                              <EyeOff className="h-4 w-4" />
                            ) : (
                              <Eye className="h-4 w-4" />
                            )}
                          </button>
                          <button
                            onClick={() => setDeleteConfirmId(d.id)}
                            title="Delete dashboard"
                            className="rounded p-1.5 text-muted-foreground transition-colors hover:bg-destructive-subtle hover:text-destructive-strong"
                          >
                            <Trash2 className="h-4 w-4" />
                          </button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </>
  )
}
