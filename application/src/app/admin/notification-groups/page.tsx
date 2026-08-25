'use client'

/**
 * Notification groups management page.
 *
 * A notification group is a reusable set of destinations used by pipeline
 * monitoring: Slack / Teams / Google Chat webhooks, email users, and SMS users
 * (users need a phone number). Groups are selected per pipeline connection.
 */
import { useState, useEffect, useCallback } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { Plus, Pencil, Trash2, Megaphone } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import {
  Button,
  Card,
  EmptyState,
  Field,
  Input,
  Label,
  LoadingRows,
  Modal,
  PageHeader,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableHeaderCell,
  TableRow,
} from '@/components/ui'

interface Recipient {
  id: number
  label: string
  email: string
  phone_number: string | null
}

interface Channels {
  slack: string[]
  teams: string[]
  gchat: string[]
  email: number[]
  sms: number[]
}

interface NotificationGroup {
  id: number
  name: string
  channels: Partial<Channels>
}

const EMPTY: Channels = { slack: [], teams: [], gchat: [], email: [], sms: [] }

function normalize(c: Partial<Channels> | undefined): Channels {
  return { ...EMPTY, ...(c ?? {}) }
}

function summarize(c: Partial<Channels> | undefined): string {
  const n = normalize(c)
  const parts: string[] = []
  if (n.slack.length) parts.push(`${n.slack.length} Slack`)
  if (n.teams.length) parts.push(`${n.teams.length} Teams`)
  if (n.gchat.length) parts.push(`${n.gchat.length} Google Chat`)
  if (n.email.length) parts.push(`${n.email.length} email`)
  if (n.sms.length) parts.push(`${n.sms.length} SMS`)
  return parts.length ? parts.join(' · ') : 'No destinations'
}

// ---------- Webhook list editor ----------

interface WebhookListProps {
  label: string
  urls: string[]
  onChange: (urls: string[]) => void
  placeholder: string
}

function WebhookList({ label, urls, onChange, placeholder }: WebhookListProps) {
  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <Label className="text-xs text-muted-foreground">{label}</Label>
        <Button variant="link" size="sm" onClick={() => onChange([...urls, ''])}>
          <Plus aria-hidden /> Add webhook
        </Button>
      </div>
      {urls.length === 0 ? (
        <p className="text-xs italic text-muted-foreground">None</p>
      ) : (
        <div className="space-y-1.5">
          {urls.map((url, i) => (
            <div key={i} className="flex items-center gap-1.5">
              <Input
                type="url"
                value={url}
                onChange={e => onChange(urls.map((u, j) => (j === i ? e.target.value : u)))}
                placeholder={placeholder}
                aria-label={`${label} ${i + 1}`}
                className="flex-1"
              />
              <Button
                variant="destructive-ghost"
                size="icon-sm"
                aria-label={`Remove ${label} ${i + 1}`}
                onClick={() => onChange(urls.filter((_, j) => j !== i))}
              >
                <Trash2 aria-hidden />
              </Button>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------- User multiselect ----------

interface UserPickerProps {
  label: string
  selected: number[]
  onChange: (ids: number[]) => void
  recipients: Recipient[]
  requirePhone?: boolean
}

function UserPicker({ label, selected, onChange, recipients, requirePhone }: UserPickerProps) {
  const eligible = requirePhone ? recipients.filter(r => r.phone_number) : recipients
  return (
    <div>
      <Label className="mb-1 text-xs text-muted-foreground">{label}</Label>
      {eligible.length === 0 ? (
        <p className="text-xs italic text-muted-foreground">
          {requirePhone ? 'No users have a phone number set.' : 'No users available.'}
        </p>
      ) : (
        <div className="max-h-40 divide-y divide-border overflow-y-auto rounded-lg border border-border">
          {eligible.map(r => (
            <label
              key={r.id}
              className="flex cursor-pointer items-center gap-2 px-2 py-1.5 hover:bg-accent"
            >
              <input
                type="checkbox"
                checked={selected.includes(r.id)}
                onChange={() =>
                  onChange(
                    selected.includes(r.id)
                      ? selected.filter(x => x !== r.id)
                      : [...selected, r.id],
                  )
                }
                className="h-4 w-4 rounded border-input text-primary focus:ring-ring"
              />
              <span className="truncate text-xs text-foreground">
                {r.label}
                {requirePhone && r.phone_number ? ` · ${r.phone_number}` : ` · ${r.email}`}
              </span>
            </label>
          ))}
        </div>
      )}
    </div>
  )
}

// ---------- Form modal ----------

interface GroupFormModalProps {
  editing: NotificationGroup | null
  recipients: Recipient[]
  apiFetch: ReturnType<typeof createClientFetch>
  onClose: () => void
  onSaved: () => void
}

function GroupFormModal({ editing, recipients, apiFetch, onClose, onSaved }: GroupFormModalProps) {
  const [name, setName] = useState(editing?.name ?? '')
  const [channels, setChannels] = useState<Channels>(normalize(editing?.channels))
  const [saving, setSaving] = useState(false)

  function set<K extends keyof Channels>(key: K, value: Channels[K]) {
    setChannels(prev => ({ ...prev, [key]: value }))
  }

  async function handleSave() {
    if (!name.trim()) return
    setSaving(true)
    // Drop blank webhook rows before saving.
    const clean: Channels = {
      slack: channels.slack.map(u => u.trim()).filter(Boolean),
      teams: channels.teams.map(u => u.trim()).filter(Boolean),
      gchat: channels.gchat.map(u => u.trim()).filter(Boolean),
      email: channels.email,
      sms: channels.sms,
    }
    try {
      const path = editing ? `/notification-groups/${editing.id}` : '/notification-groups'
      await apiFetch(path, {
        method: editing ? 'PUT' : 'POST',
        body: JSON.stringify({ name: name.trim(), channels: clean }),
      })
      toast.success(editing ? 'Group updated.' : 'Group created.')
      onSaved()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save group.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Modal
      open
      onClose={onClose}
      title={editing ? 'Edit Notification Group' : 'New Notification Group'}
      footer={
        <>
          <Button variant="outline" onClick={onClose} disabled={saving}>
            Cancel
          </Button>
          <Button onClick={() => void handleSave()} disabled={!name.trim()} isLoading={saving}>
            {editing ? 'Save' : 'Create'}
          </Button>
        </>
      }
    >
      <div className="space-y-4">
        <Field label="Group name" htmlFor="group-name" required>
          <Input
            id="group-name"
            value={name}
            onChange={e => setName(e.target.value)}
            placeholder="Data Team Alerts"
          />
        </Field>

        <WebhookList
          label="Slack webhooks"
          urls={channels.slack}
          onChange={v => set('slack', v)}
          placeholder="https://hooks.slack.com/services/…"
        />
        <WebhookList
          label="Microsoft Teams webhooks"
          urls={channels.teams}
          onChange={v => set('teams', v)}
          placeholder="https://…webhook.office.com/…"
        />
        <WebhookList
          label="Google Chat webhooks"
          urls={channels.gchat}
          onChange={v => set('gchat', v)}
          placeholder="https://chat.googleapis.com/v1/spaces/…"
        />
        <UserPicker
          label="Email recipients"
          selected={channels.email}
          onChange={v => set('email', v)}
          recipients={recipients}
        />
        <UserPicker
          label="SMS recipients (require phone number)"
          selected={channels.sms}
          onChange={v => set('sms', v)}
          recipients={recipients}
          requirePhone
        />
      </div>
    </Modal>
  )
}

// ---------- Page ----------

export default function NotificationGroupsPage() {
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [groups, setGroups] = useState<NotificationGroup[]>([])
  const [recipients, setRecipients] = useState<Recipient[]>([])
  const [loading, setLoading] = useState(true)
  const [formOpen, setFormOpen] = useState(false)
  const [editing, setEditing] = useState<NotificationGroup | null>(null)

  const load = useCallback(async () => {
    if (!session?.user?.access_token) return
    try {
      const [grps, recs] = await Promise.all([
        apiFetch<NotificationGroup[]>('/notification-groups'),
        apiFetch<Recipient[]>('/notification-recipients').catch(() => [] as Recipient[]),
      ])
      setGroups(grps)
      setRecipients(recs)
    } catch {
      toast.error('Failed to load notification groups.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  useEffect(() => {
    void load()
  }, [load])

  async function handleDelete(g: NotificationGroup) {
    if (!confirm(`Delete "${g.name}"?`)) return
    try {
      await apiFetch(`/notification-groups/${g.id}`, { method: 'DELETE' })
      setGroups(prev => prev.filter(x => x.id !== g.id))
      toast.success('Group deleted.')
    } catch {
      toast.error('Failed to delete group.')
    }
  }

  function openNew() {
    setEditing(null)
    setFormOpen(true)
  }

  return (
    <div className="space-y-6">
      <PageHeader
        title="Notification Groups"
        description="Reusable destination sets for pipeline monitoring alerts. Select a group per pipeline connection under its Notifications tab."
        actions={
          <Button onClick={openNew}>
            <Plus aria-hidden />
            New group
          </Button>
        }
      />

      {loading ? (
        <Card className="p-6">
          <LoadingRows rows={4} />
        </Card>
      ) : groups.length === 0 ? (
        <Card className="p-6">
          <EmptyState
            icon={Megaphone}
            title="No notification groups yet"
            description="A group bundles the Slack, Teams, email, and SMS destinations an alert should reach, so you pick one group per pipeline instead of re-entering webhooks. Create your first group to start routing alerts."
            action={
              <Button onClick={openNew}>
                <Plus aria-hidden />
                New group
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
                  <TableHeaderCell>Destinations</TableHeaderCell>
                  <TableHeaderCell align="right">Actions</TableHeaderCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {groups.map(g => (
                  <TableRow key={g.id}>
                    <TableCell className="font-medium">{g.name}</TableCell>
                    <TableCell muted>{summarize(g.channels)}</TableCell>
                    <TableCell align="right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label={`Edit ${g.name}`}
                          onClick={() => {
                            setEditing(g)
                            setFormOpen(true)
                          }}
                        >
                          <Pencil aria-hidden />
                        </Button>
                        <Button
                          variant="destructive-ghost"
                          size="icon-sm"
                          aria-label={`Delete ${g.name}`}
                          onClick={() => void handleDelete(g)}
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
        <GroupFormModal
          editing={editing}
          recipients={recipients}
          apiFetch={apiFetch}
          onClose={() => setFormOpen(false)}
          onSaved={() => void load()}
        />
      )}
    </div>
  )
}
