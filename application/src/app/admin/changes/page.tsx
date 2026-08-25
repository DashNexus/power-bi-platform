'use client'

/**
 * Global change-history feed.
 *
 * Org-wide record of every create/update/delete (AI and human) from the change
 * ledger, with source/type filters and one-click revert. Admin-gated by the
 * admin layout; the feed API additionally requires the changes.view permission.
 */
import { useCallback, useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { RotateCcw, Sparkles, User, Eye, History } from 'lucide-react'
import { toast } from 'sonner'
import { createClientFetch } from '@/lib/api'
import { StatePreview } from '@/components/changes/StatePreview'
import type { ChangeRecord } from '@/components/changes/types'
import {
  Badge,
  Button,
  Card,
  EmptyState,
  Input,
  LoadingRows,
  PageHeader,
  Select,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '@/components/ui'

const ACTIONS = [
  { value: '', label: 'All actions' },
  { value: 'create', label: 'Created' },
  { value: 'update', label: 'Updated' },
  { value: 'delete', label: 'Deleted' },
]

interface ResourceTypeOption {
  value: string
  label: string
}

/**
 * Shown until the real list arrives, and if the request fails. The options
 * themselves come from the API — this list used to be hand-written and had
 * drifted to name resources that do not exist in this build (projects, tasks,
 * tickets) while omitting the ones that do.
 */
const ALL_TYPES: ResourceTypeOption = { value: '', label: 'All types' }

const SOURCES = [
  { value: '', label: 'AI & human' },
  { value: 'ai', label: 'AI only' },
  { value: 'user', label: 'Human only' },
]

export default function ChangesPage() {
  const { data: session } = useSession()
  const [records, setRecords] = useState<ChangeRecord[]>([])
  const [resourceTypes, setResourceTypes] = useState<ResourceTypeOption[]>([ALL_TYPES])
  const [loading, setLoading] = useState(true)
  const [source, setSource] = useState('')
  const [resourceType, setResourceType] = useState('')
  const [action, setAction] = useState('')
  const [actor, setActor] = useState('')
  const [actorApplied, setActorApplied] = useState('')
  const [reverting, setReverting] = useState<number | null>(null)
  const [preview, setPreview] = useState<ChangeRecord | null>(null)

  const hasFilters = Boolean(source || resourceType || action || actorApplied.trim())

  const load = useCallback(async () => {
    if (!session?.user?.access_token) return
    const fetcher = createClientFetch(session.user.access_token)
    setLoading(true)
    try {
      const params: Record<string, string> = {}
      if (source) params.source = source
      if (resourceType) params.resource_type = resourceType
      if (action) params.action = action
      if (actorApplied.trim()) params.actor = actorApplied.trim()
      const data = await fetcher<ChangeRecord[]>('/changes', { searchParams: params })
      setRecords(data)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to load changes')
      setRecords([])
    } finally {
      setLoading(false)
    }
  }, [session?.user?.access_token, source, resourceType, action, actorApplied])

  useEffect(() => {
    void load()
  }, [load])

  useEffect(() => {
    if (!session?.user?.access_token) return
    const fetcher = createClientFetch(session.user.access_token)
    fetcher<ResourceTypeOption[]>('/changes/resource-types')
      .then(types => setResourceTypes([ALL_TYPES, ...types]))
      // The feed still works with only "All types"; no toast for a filter menu.
      .catch(() => undefined)
  }, [session?.user?.access_token])

  function clearFilters() {
    setSource('')
    setResourceType('')
    setAction('')
    setActor('')
    setActorApplied('')
  }

  async function revert(record: ChangeRecord) {
    if (!session?.user?.access_token || reverting) return
    const fetcher = createClientFetch(session.user.access_token)
    setReverting(record.id)
    try {
      // Group revert whenever the action wrote more than one row — a deleted
      // dashboard also deletes its filters and shares, and reverting only the
      // parent row would bring it back stripped. Previously this keyed off
      // source === 'ai', so human multi-row deletes reverted partially.
      const path =
        record.correlation_id && record.correlation_size > 1
          ? `/changes/correlation/${record.correlation_id}/revert`
          : `/changes/${record.id}/revert`
      await fetcher(path, { method: 'POST' })
      toast.success('Change reverted')
      await load()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Revert failed')
    } finally {
      setReverting(null)
    }
  }

  return (
    <div className="mx-auto w-full space-y-6">
      <PageHeader
        title="Change History"
        description="Every change made across the platform — by people and by AI — with revert."
      />

      <Card className="flex flex-wrap gap-3 p-4">
        <Select
          value={source}
          onChange={e => setSource(e.target.value)}
          aria-label="Filter by source"
          className="w-auto"
        >
          {SOURCES.map(s => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </Select>
        <Select
          value={resourceType}
          onChange={e => setResourceType(e.target.value)}
          aria-label="Filter by resource type"
          className="w-auto"
        >
          {resourceTypes.map(t => (
            <option key={t.value} value={t.value}>
              {t.label}
            </option>
          ))}
        </Select>
        <Select
          value={action}
          onChange={e => setAction(e.target.value)}
          aria-label="Filter by action"
          className="w-auto"
        >
          {ACTIONS.map(a => (
            <option key={a.value} value={a.value}>
              {a.label}
            </option>
          ))}
        </Select>
        <Input
          value={actor}
          onChange={e => setActor(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && setActorApplied(actor)}
          onBlur={() => setActorApplied(actor)}
          placeholder="Search by user…"
          aria-label="Filter by user"
          className="w-auto"
        />
        {hasFilters && (
          <Button variant="ghost" size="sm" onClick={clearFilters}>
            Clear filters
          </Button>
        )}
      </Card>

      {loading ? (
        <Card className="p-6">
          <LoadingRows rows={5} />
        </Card>
      ) : records.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={History}
            title={hasFilters ? 'No changes match these filters' : 'No changes recorded yet'}
            description={
              hasFilters
                ? 'Nothing in the ledger matches the current filters. Widen or clear them to see more history.'
                : 'Every create, update, and delete across the platform is recorded here — by people and by AI. Edit a project, client, or diagram and it will show up.'
            }
            action={
              hasFilters ? (
                <Button variant="outline" onClick={clearFilters}>
                  Clear filters
                </Button>
              ) : undefined
            }
          />
        </Card>
      ) : (
        <Card className="overflow-hidden">
          <TableContainer>
            <Table>
              <TableHead>
                <TableRow>
                  <TableHeaderCell>Source</TableHeaderCell>
                  <TableHeaderCell>Action</TableHeaderCell>
                  <TableHeaderCell>Resource</TableHeaderCell>
                  <TableHeaderCell>When</TableHeaderCell>
                  <TableHeaderCell align="right">Actions</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {records.map(record => (
                  <TableRow key={record.id}>
                    <TableCell>
                      {record.source === 'ai' ? (
                        <Badge tone="assistant">
                          <Sparkles aria-hidden /> AI
                        </Badge>
                      ) : (
                        <Badge>
                          <User aria-hidden /> {record.actor_name ?? 'User'}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="text-xs uppercase tracking-wide" muted>
                      {record.action}
                    </TableCell>
                    <TableCell>
                      <span className="text-xs text-muted-foreground">{record.resource_type}</span>{' '}
                      {record.resource_name ?? `#${record.resource_id}`}
                    </TableCell>
                    <TableCell className="text-xs" muted>
                      {new Date(record.created_at).toLocaleString()}
                    </TableCell>
                    <TableCell align="right">
                      <div className="flex items-center justify-end gap-1">
                        <Button variant="ghost" size="sm" onClick={() => setPreview(record)}>
                          <Eye aria-hidden /> View
                        </Button>
                        {record.reverted_at ? (
                          <span className="px-2 text-xs text-muted-foreground">reverted</span>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => void revert(record)}
                            disabled={reverting !== null}
                            isLoading={reverting === record.id}
                          >
                            {reverting !== record.id && <RotateCcw aria-hidden />}
                            Revert
                          </Button>
                        )}
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        </Card>
      )}

      {preview && <StatePreview record={preview} onClose={() => setPreview(null)} />}
    </div>
  )
}
