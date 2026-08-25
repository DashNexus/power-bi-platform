'use client'

/**
 * Data pipeline connections management page.
 *
 * Admins create, edit, test, delete, and share connections to pipeline
 * orchestrators (Prefect, Airflow, Azure Data Factory, and planned
 * integrations). The connection form is driven by each provider's field
 * metadata from the API, so new providers appear automatically. Secrets are
 * write-only in the UI.
 */
import { useState, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { Plus, Pencil, Trash2, Zap, Workflow, Users } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { ShareResourceDialog } from '@/components/admin/ShareResourceDialog'
import {
  ProviderConnectionForm,
  type ConnectionPayload,
  type ProviderGroup,
  type ProviderMetaBase,
} from '@/components/admin/ProviderConnectionForm'
import {
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

interface PipelineConnection {
  id: number
  name: string
  provider: string
  provider_label: string
  provider_implemented: boolean
  config: Record<string, string>
  is_active: boolean
  has_secret: boolean
  created_at: string
}

interface ProviderMeta extends ProviderMetaBase {
  docs_url: string
}

/** Available providers first, then the catalogued-but-unbuilt ones. */
function providerGroups(providers: ProviderMeta[]): ProviderGroup[] {
  return [
    {
      label: 'Available',
      options: providers.filter(p => p.implemented).map(p => ({ key: p.key, label: p.label })),
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

export default function AdminDataPipelinesPage() {
  const { data: session } = useSession()
  const router = useRouter()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [connections, setConnections] = useState<PipelineConnection[]>([])
  const [providers, setProviders] = useState<ProviderMeta[]>([])
  const [loading, setLoading] = useState(true)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<PipelineConnection | null>(null)
  const [shareConn, setShareConn] = useState<PipelineConnection | null>(null)
  const [testingId, setTestingId] = useState<number | null>(null)

  const load = useCallback(async () => {
    if (!session?.user?.access_token) return
    try {
      const [conns, provs] = await Promise.all([
        apiFetch<PipelineConnection[]>('/admin/data-pipelines'),
        apiFetch<ProviderMeta[]>('/data-pipelines/providers'),
      ])
      setConnections(conns)
      setProviders(provs)
    } catch {
      toast.error('Failed to load pipeline connections.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  useEffect(() => {
    void load()
  }, [load])

  async function handleSave(payload: ConnectionPayload) {
    try {
      if (editing) {
        await apiFetch(`/admin/data-pipelines/${editing.id}`, {
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
        await apiFetch('/admin/data-pipelines', {
          method: 'POST',
          body: JSON.stringify(payload),
        })
        toast.success('Connection created.')
      }
      void load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save connection.')
      throw err
    }
  }

  async function handleDelete(conn: PipelineConnection) {
    if (!confirm(`Delete "${conn.name}"? This cannot be undone.`)) return
    try {
      await apiFetch(`/admin/data-pipelines/${conn.id}`, { method: 'DELETE' })
      setConnections(prev => prev.filter(c => c.id !== conn.id))
      toast.success('Connection deleted.')
    } catch {
      toast.error('Failed to delete connection.')
    }
  }

  async function handleTest(conn: PipelineConnection) {
    setTestingId(conn.id)
    try {
      const result = await apiFetch<{ ok: boolean; error?: string; pipeline_count?: number }>(
        `/admin/data-pipelines/${conn.id}/test`,
        { method: 'POST' },
      )
      if (result.ok) {
        toast.success(
          result.pipeline_count != null
            ? `Connected — ${result.pipeline_count} pipelines found.`
            : 'Connection successful.',
        )
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
        title="Data Pipelines"
        description="Connect to pipeline orchestrators and share them with roles. Shared connections appear on the Resources page and can be added to the nav."
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
            icon={Workflow}
            title="No pipeline connections yet"
            description="Connect an orchestrator — Prefect, Airflow, or Azure Data Factory — to monitor its runs here and route failure alerts to a notification group."
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
                  <TableRow
                    key={conn.id}
                    interactive
                    onClick={() => router.push(`/pipelines/${conn.id}`)}
                    title="View pipelines and run history"
                  >
                    <TableCell className="font-medium text-primary">{conn.name}</TableCell>
                    <TableCell>
                      <Badge tone="info">{conn.provider_label}</Badge>
                    </TableCell>
                    <TableCell>
                      <Badge tone={conn.is_active ? 'success' : 'neutral'}>
                        {conn.is_active ? 'Active' : 'Inactive'}
                      </Badge>
                    </TableCell>
                    <TableCell align="right" onClick={e => e.stopPropagation()}>
                      <div className="flex items-center justify-end gap-1">
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
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Share ${conn.name}`}
                          title="Share with roles"
                          onClick={() => setShareConn(conn)}
                        >
                          <Users aria-hidden />
                        </Button>
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
          title={editing ? 'Edit Pipeline Connection' : 'New Pipeline Connection'}
          namePlaceholder="Production Prefect"
          providers={providers}
          providerGroups={providerGroups(providers)}
          editing={editing}
          onSubmit={handleSave}
          onClose={() => setFormOpen(false)}
        />
      )}

      {shareConn && (
        <ShareResourceDialog
          resourceLabel="Data Pipeline"
          resourceName={shareConn.name}
          permissionsPath={`/admin/data-pipelines/${shareConn.id}/permissions`}
          apiFetch={apiFetch}
          onClose={() => setShareConn(null)}
        />
      )}
    </div>
  )
}
