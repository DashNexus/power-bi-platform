'use client'

/**
 * BI (embed) connections management page.
 *
 * Admins create, edit, test, and delete connections to BI/embedding platforms
 * (Power BI, Tableau, and planned integrations), plus enable single-instance
 * public surfaces (Tableau Public, Looker Studio). The form is driven by each
 * provider's field metadata from the API; secrets are write-only in the UI.
 */
import { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { Plus, Pencil, Trash2, Zap, BarChart3, Globe } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import {
  ProviderConnectionForm,
  type ConnectionPayload,
  type ProviderGroup,
  type ProviderMetaBase,
} from '@/components/admin/ProviderConnectionForm'
import {
  Alert,
  Badge,
  Button,
  Card,
  EmptyState,
  LoadingRows,
  PageHeader,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '@/components/ui'

// ---------- Types ----------

interface BiConnection {
  id: number
  name: string
  provider: string
  provider_label: string
  provider_implemented: boolean
  requires_auth: boolean
  singleton: boolean
  config: Record<string, string>
  is_active: boolean
  has_secret: boolean
}

interface ProviderMeta extends ProviderMetaBase {
  singleton: boolean
  requires_auth: boolean
  docs_url: string
}

/**
 * Credentialed providers, then public single-connection surfaces, then planned.
 *
 * A singleton whose one connection already exists is disabled unless it is the
 * connection being edited.
 */
function providerGroups(
  providers: ProviderMeta[],
  existing: Set<string>,
  isEditing: boolean,
): ProviderGroup[] {
  const selectable = providers.filter(p => p.implemented)
  return [
    {
      label: 'Available',
      options: selectable
        .filter(p => p.requires_auth)
        .map(p => ({ key: p.key, label: p.label })),
    },
    {
      label: 'Public (single connection, no login)',
      options: selectable
        .filter(p => !p.requires_auth)
        .map(p => {
          const taken = !isEditing && existing.has(p.key)
          return {
            key: p.key,
            label: taken ? `${p.label} (already added)` : p.label,
            disabled: taken,
          }
        }),
    },
    {
      label: 'Coming soon',
      options: providers
        .filter(p => !p.implemented)
        .map(p => ({ key: p.key, label: `${p.label} (coming soon)`, disabled: true })),
    },
  ]
}

// ---------- Page ----------

export default function AdminBiConnectionsPage() {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [connections, setConnections] = useState<BiConnection[]>([])
  const [providers, setProviders] = useState<ProviderMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<BiConnection | null>(null)
  const [testingId, setTestingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    if (!session?.user?.access_token) return
    try {
      const [conns, provs] = await Promise.all([
        apiFetch<BiConnection[]>('/bi-connections'),
        apiFetch<ProviderMeta[]>('/bi-connections/providers'),
      ])
      setConnections(conns)
      setProviders(provs)
    } catch {
      toast.error('Failed to load BI connections.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  useEffect(() => {
    void load()
  }, [load])

  const existingProviders = new Set(connections.map(c => c.provider))

  async function handleSave(payload: ConnectionPayload) {
    try {
      if (editing) {
        await apiFetch(`/bi-connections/${editing.id}`, {
          method: 'PUT',
          body: JSON.stringify({
            name: payload.name,
            config: payload.config,
            secret: payload.secret,
            is_active: payload.is_active,
          }),
        })
        toast.success('Connection updated.')
      } else {
        await apiFetch('/bi-connections', { method: 'POST', body: JSON.stringify(payload) })
        toast.success('Connection created.')
      }
      void load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save connection.')
      throw err
    }
  }

  async function handleDelete(conn: BiConnection) {
    if (!confirm(`Delete "${conn.name}"? This cannot be undone.`)) return
    try {
      await apiFetch(`/bi-connections/${conn.id}`, { method: 'DELETE' })
      setConnections(prev => prev.filter(c => c.id !== conn.id))
      toast.success('Connection deleted.')
    } catch {
      toast.error('Failed to delete connection.')
    }
  }

  async function handleTest(conn: BiConnection) {
    setTestingId(conn.id)
    try {
      const result = await apiFetch<{
        ok: boolean
        error?: string
        note?: string
        workspace_count?: number
        server_version?: string
      }>(`/bi-connections/${conn.id}/test`, { method: 'POST' })
      if (result.ok) {
        const detail =
          result.note ||
          (result.workspace_count != null ? `${result.workspace_count} workspaces found.` : '') ||
          (result.server_version ? `Tableau Server ${result.server_version}.` : '')
        toast.success(detail ? `Connected — ${detail}` : 'Connection successful.')
      } else {
        toast.error(result.error || 'Connection failed.')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Connection test failed.')
    } finally {
      setTestingId(null)
    }
  }

  function openNew() {
    setEditing(null)
    setFormOpen(true)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="BI Connections"
        description="Connect Power BI, Tableau, and other BI platforms for embedding. Add as many as you need and give each a name. Public surfaces (Tableau Public, Looker Studio) allow one connection each."
        actions={
          <Button onClick={openNew}>
            <Plus aria-hidden />
            New connection
          </Button>
        }
      />

      {loading ? (
        <Card className="p-6">
          <LoadingRows rows={4} />
        </Card>
      ) : connections.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={BarChart3}
            title="No BI connections yet"
            description="A BI connection lets you embed Power BI reports, Tableau views, and public dashboards inside the platform. Add your first one to start building embedded dashboards."
            action={
              <Button onClick={openNew}>
                <Plus aria-hidden />
                New connection
              </Button>
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Name</TableHeaderCell>
                  <TableHeaderCell>Provider</TableHeaderCell>
                  <TableHeaderCell>Status</TableHeaderCell>
                  <TableHeaderCell align="right">Actions</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {connections.map(conn => (
                  <TableRow key={conn.id}>
                    <TableCell className="font-medium">{conn.name}</TableCell>
                    <TableCell>
                      <Badge tone="assistant">
                        {!conn.requires_auth && <Globe aria-hidden />}
                        {conn.provider_label}
                      </Badge>
                    </TableCell>
                    <TableCell>
                      <Badge tone={conn.is_active ? 'success' : 'neutral'}>
                        {conn.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </TableCell>
                    <TableCell align="right">
                      <div className="flex items-center justify-end gap-1">
                        {conn.requires_auth && (
                          <Button
                            variant="ghost"
                            size="icon-sm"
                            aria-label={`Test ${conn.name}`}
                            title="Test connection"
                            onClick={() => void handleTest(conn)}
                            isLoading={testingId === conn.id}
                          >
                            {testingId !== conn.id && <Zap aria-hidden />}
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Edit ${conn.name}`}
                          title="Edit"
                          onClick={() => {
                            setEditing(conn)
                            setFormOpen(true)
                          }}
                        >
                          <Pencil aria-hidden />
                        </Button>
                        <Button
                          variant="destructive-ghost"
                          size="icon-sm"
                          aria-label={`Delete ${conn.name}`}
                          title="Delete"
                          onClick={() => void handleDelete(conn)}
                        >
                          <Trash2 aria-hidden />
                        </Button>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}

      {formOpen && (
        <ProviderConnectionForm
          title={editing ? 'Edit BI Connection' : 'New BI Connection'}
          namePlaceholder="Marketing Power BI"
          providers={providers}
          providerGroups={providerGroups(providers, existingProviders, Boolean(editing))}
          editing={editing}
          notice={provider =>
            provider.requires_auth ? null : (
              <Alert tone="info">
                {provider.label} embeds publicly shared content — no credentials are required.
                Toggle Active to enable or disable it.
              </Alert>
            )
          }
          onSubmit={handleSave}
          onClose={() => setFormOpen(false)}
        />
      )}
    </div>
  )
}
