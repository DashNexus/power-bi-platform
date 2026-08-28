'use client'

/**
 * Interactive user management table for admins.
 *
 * Supports creating users directly, editing profile fields, role assignment,
 * activate/deactivate, and the invitation lifecycle.
 *
 * An invitation is issued once and reachable two ways: the API mails the link
 * and returns the same link here, so a deployment with no SMTP — or an admin
 * who would rather send it themselves — can copy it out of the dialog or off
 * the invitations table. Both point at the same single-use token, which is why
 * Resend replaces it rather than re-sending the old one.
 */
import { useState, useCallback, useEffect } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { createClientFetch } from '@/lib/api'
import { Avatar, Select } from '@/components/ui'

interface User {
  id: number
  email: string
  display_name: string | null
  job_title?: string | null
  avatar_url?: string | null
  first_name: string | null
  last_name: string | null
  phone_number: string | null
  is_active: boolean
  totp_enabled: boolean
  last_login_at: string | null
  created_at: string
  roles: string[]
}

interface Role {
  id: number
  name: string
  description: string | null
  is_system: boolean
}

interface PaginatedUsers {
  items: User[]
  total: number
  page: number
  page_size: number
}

/** Mirrors `InviteResponse` in `api/app/schemas/invite.py`. */
interface Invite {
  id: number
  email: string
  first_name: string | null
  last_name: string | null
  role_id: number | null
  role_name: string | null
  status: 'pending' | 'accepted' | 'expired'
  invite_url: string
  expires_at: string
  accepted_at: string | null
  created_at: string
  email_sent: boolean | null
  email_error: string | null
}

interface UsersClientProps {
  initialUsers: User[]
  initialTotal: number
  roles: Role[]
}

// ---------- Reset Password Dialog ----------

interface ResetPasswordDialogProps {
  user: User
  onClose: () => void
  apiFetch: ReturnType<typeof createClientFetch>
}

function ResetPasswordDialog({ user, onClose, apiFetch }: ResetPasswordDialogProps) {
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (password.length < 8) { setError('Password must be at least 8 characters.'); return }
    if (password !== confirm) { setError('Passwords do not match.'); return }
    setSaving(true)
    setError(null)
    try {
      await apiFetch(`/admin/users/${user.id}/set-password`, {
        method: 'POST',
        body: JSON.stringify({ new_password: password }),
      })
      toast.success(`Password updated for ${user.email}.`)
      onClose()
    } catch {
      setError('Failed to update password.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-sm rounded-xl bg-card shadow-xl p-6">
        <h2 className="text-base font-semibold text-foreground mb-1">Reset Password</h2>
        <p className="text-sm text-muted-foreground mb-4">Set a new password for <strong>{user.email}</strong>.</p>
        <form onSubmit={e => void handleSubmit(e)} className="space-y-3">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">New password</label>
            <input
              type="password"
              value={password}
              onChange={e => setPassword(e.target.value)}
              className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              autoFocus
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Confirm password</label>
            <input
              type="password"
              value={confirm}
              onChange={e => setConfirm(e.target.value)}
              className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          {error && <p className="text-xs text-destructive-strong">{error}</p>}
          <div className="flex justify-end gap-2 pt-1">
            <button type="button" onClick={onClose} className="rounded px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent">Cancel</button>
            <button type="submit" disabled={saving} className="rounded bg-primary px-3 py-1.5 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50">
              {saving ? 'Saving…' : 'Set Password'}
            </button>
          </div>
        </form>
      </div>
    </div>
  )
}

// ---------- Delete Confirmation Dialog ----------

interface DeleteUserDialogProps {
  user: User
  onClose: () => void
  onDeleted: () => void
  apiFetch: ReturnType<typeof createClientFetch>
}

function DeleteUserDialog({ user, onClose, onDeleted, apiFetch }: DeleteUserDialogProps) {
  const [input, setInput] = useState('')
  const [deleting, setDeleting] = useState(false)

  async function handleDelete() {
    setDeleting(true)
    try {
      await apiFetch(`/admin/users/${user.id}`, { method: 'DELETE' })
      toast.success(`${user.email} has been deactivated.`)
      onDeleted()
      onClose()
    } catch {
      toast.error('Failed to deactivate user.')
    } finally {
      setDeleting(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40">
      <div className="w-full max-w-sm rounded-xl bg-card shadow-xl p-6">
        <h2 className="text-base font-semibold text-foreground mb-1">Delete User</h2>
        <p className="text-sm text-muted-foreground mb-3">
          This will deactivate <strong>{user.email}</strong> and prevent them from signing in.
          Type their email address to confirm.
        </p>
        <input
          type="text"
          value={input}
          onChange={e => setInput(e.target.value)}
          placeholder={user.email}
          className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-red-500 mb-3"
          autoFocus
        />
        <div className="flex justify-end gap-2">
          <button type="button" onClick={onClose} className="rounded px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent">Cancel</button>
          <button
            type="button"
            disabled={input !== user.email || deleting}
            onClick={() => void handleDelete()}
            className="rounded bg-destructive px-3 py-1.5 text-sm font-medium text-white hover:bg-destructive/90 disabled:opacity-50"
          >
            {deleting ? 'Deleting…' : 'Delete User'}
          </button>
        </div>
      </div>
    </div>
  )
}

function formatDate(iso: string | null): string {
  if (!iso) return 'Never'
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

function displayName(user: User): string {
  if (user.first_name || user.last_name) {
    return [user.first_name, user.last_name].filter(Boolean).join(' ')
  }
  return user.display_name ?? '—'
}

function RoleBadge({ role }: { role: string }) {
  const colours: Record<string, string> = {
    superadmin: 'bg-destructive-subtle text-destructive-strong',
    admin: 'bg-purple-100 text-assistant',
    manager: 'bg-orange-100 text-orange-700',
    analyst: 'bg-primary-subtle text-info-strong',
    viewer: 'bg-muted text-muted-foreground',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${colours[role] ?? 'bg-muted text-muted-foreground'}`}
    >
      {role}
    </span>
  )
}

// ---------- Profile field group ----------

interface ProfileFieldsProps {
  firstName: string
  lastName: string
  displayName: string
  phone: string
  onFirstName: (v: string) => void
  onLastName: (v: string) => void
  onDisplayName: (v: string) => void
  onPhone: (v: string) => void
}

function ProfileFields({
  firstName,
  lastName,
  displayName: dn,
  phone,
  onFirstName,
  onLastName,
  onDisplayName,
  onPhone,
}: ProfileFieldsProps) {
  return (
    <>
      <div className="grid grid-cols-2 gap-3">
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">First name</label>
          <input
            type="text"
            value={firstName}
            onChange={e => onFirstName(e.target.value)}
            placeholder="Jane"
            className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Last name</label>
          <input
            type="text"
            value={lastName}
            onChange={e => onLastName(e.target.value)}
            placeholder="Smith"
            className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>
      </div>

      <div>
        <label className="block text-sm font-medium text-foreground mb-1">
          Display name <span className="font-normal text-muted-foreground">(optional override)</span>
        </label>
        <input
          type="text"
          value={dn}
          onChange={e => onDisplayName(e.target.value)}
          placeholder="Auto-derived from first + last name"
          className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

      <div>
        <label className="block text-sm font-medium text-foreground mb-1">
          Phone number <span className="font-normal text-muted-foreground">(for SMS notifications)</span>
        </label>
        <input
          type="tel"
          value={phone}
          onChange={e => onPhone(e.target.value)}
          placeholder="+14155550123"
          className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
        />
      </div>

    </>
  )
}

// ---------- Edit Modal ----------

interface EditModalProps {
  user: User
  roles: Role[]
  onClose: () => void
  onSaved: (updated: User) => void
  apiFetch: ReturnType<typeof createClientFetch>
}

function EditModal({ user, roles, onClose, onSaved, apiFetch }: EditModalProps) {
  const [firstName, setFirstName] = useState(user.first_name ?? '')
  const [lastName, setLastName] = useState(user.last_name ?? '')
  const [displayNameVal, setDisplayNameVal] = useState(user.display_name ?? '')
  const [phone, setPhone] = useState(user.phone_number ?? '')
  const [isActive, setIsActive] = useState(user.is_active)
  const [selectedRoleId, setSelectedRoleId] = useState<number | null>(
    user.roles
      .map(name => roles.find(r => r.name === name)?.id)
      .filter((id): id is number => id !== undefined)[0] ?? null,
  )
  const [saving, setSaving] = useState(false)

  async function handleSave() {
    setSaving(true)
    try {
      const updated = await apiFetch<User>(`/admin/users/${user.id}`, {
        method: 'PUT',
        body: JSON.stringify({
          first_name: firstName || null,
          last_name: lastName || null,
          display_name: displayNameVal || null,
          phone_number: phone || null,
          is_active: isActive,
        }),
      })
      await apiFetch(`/admin/users/${user.id}/roles`, {
        method: 'PUT',
        body: JSON.stringify(selectedRoleId !== null ? [selectedRoleId] : []),
      })
      const roleName = roles.find(r => r.id === selectedRoleId)?.name
      onSaved({ ...updated, roles: roleName ? [roleName] : [] })
      toast.success('User updated.')
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to save user.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-card p-6 shadow-xl space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-base font-semibold text-foreground">Edit User</h3>
        <p className="text-sm text-muted-foreground">{user.email}</p>

        <ProfileFields
          firstName={firstName}
          lastName={lastName}
          displayName={displayNameVal}
          phone={phone}
          onFirstName={setFirstName}
          onLastName={setLastName}
          onDisplayName={setDisplayNameVal}
          onPhone={setPhone}
        />

        {/* Active toggle */}
        <div className="flex items-center gap-3">
          <input
            id="edit-is-active"
            type="checkbox"
            checked={isActive}
            onChange={e => setIsActive(e.target.checked)}
            className="h-4 w-4 rounded border-border-strong text-primary focus:ring-ring"
          />
          <label htmlFor="edit-is-active" className="text-sm text-foreground">
            Account active
          </label>
        </div>

        {/* Role picker */}
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Role</label>
          <Select
            value={selectedRoleId ?? ''}
            onChange={e => setSelectedRoleId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">No role</option>
            {roles.map(role => (
              <option key={role.id} value={role.id}>
                {role.name}{role.description ? ` — ${role.description}` : ''}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="rounded border px-4 py-2 text-sm hover:bg-accent"
          >
            Cancel
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save Changes'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------- Create User Dialog ----------

interface CreateUserDialogProps {
  roles: Role[]
  onClose: () => void
  onCreated: () => void
  apiFetch: ReturnType<typeof createClientFetch>
}

function CreateUserDialog({ roles, onClose, onCreated, apiFetch }: CreateUserDialogProps) {
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [displayNameVal, setDisplayNameVal] = useState('')
  const [phone, setPhone] = useState('')
  const [roleId, setRoleId] = useState<number | null>(null)
  const [saving, setSaving] = useState(false)

  async function handleCreate() {
    if (!email.trim()) {
      toast.error('Email is required.')
      return
    }
    setSaving(true)
    try {
      await apiFetch('/admin/users', {
        method: 'POST',
        body: JSON.stringify({
          email: email.trim(),
          password: password || null,
          first_name: firstName || null,
          last_name: lastName || null,
          display_name: displayNameVal || null,
          phone_number: phone || null,
          role_ids: roleId !== null ? [roleId] : [],
        }),
      })
      toast.success(`User ${email.trim()} created.`)
      onCreated()
      onClose()
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create user.')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-card p-6 shadow-xl space-y-4 max-h-[90vh] overflow-y-auto">
        <h3 className="text-base font-semibold text-foreground">Create User</h3>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">
            Email address <span className="text-destructive">*</span>
          </label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="name@company.com"
            className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">
            Password <span className="font-normal text-muted-foreground">(optional — user can reset later)</span>
          </label>
          <input
            type="password"
            value={password}
            onChange={e => setPassword(e.target.value)}
            placeholder="Leave blank to require password reset"
            autoComplete="new-password"
            className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <ProfileFields
          firstName={firstName}
          lastName={lastName}
          displayName={displayNameVal}
          phone={phone}
          onFirstName={setFirstName}
          onLastName={setLastName}
          onDisplayName={setDisplayNameVal}
          onPhone={setPhone}
        />

        {/* Role picker */}
        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Role</label>
          <Select
            value={roleId ?? ''}
            onChange={e => setRoleId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">No role</option>
            {roles.map(role => (
              <option key={role.id} value={role.id}>
                {role.name}{role.description ? ` — ${role.description}` : ''}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="rounded border px-4 py-2 text-sm hover:bg-accent"
          >
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={saving || !email.trim()}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          >
            {saving ? 'Creating…' : 'Create User'}
          </button>
        </div>
      </div>
    </div>
  )
}

/**
 * An invitation's state.
 *
 * "Expired" is deliberately distinct from "pending": both mean no account
 * exists yet, but only one of them means the invitee is holding a link that
 * will not work, which is the case an admin has to act on.
 */
function InviteStatusBadge({ status }: { status: Invite['status'] }) {
  const tones: Record<Invite['status'], string> = {
    accepted: 'bg-success-subtle text-success-strong',
    pending: 'bg-warning-subtle text-warning-strong',
    expired: 'bg-muted text-muted-foreground',
  }
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${tones[status]}`}
    >
      {status.charAt(0).toUpperCase() + status.slice(1)}
    </span>
  )
}

// ---------- Invite link ----------

/**
 * Copies an invitation link to the clipboard, confirming in place.
 *
 * `navigator.clipboard` needs a secure context, and an admin console served
 * over plain HTTP on a LAN is not one — so the link stays visible and
 * selectable, and a failed copy says to copy it by hand rather than nothing.
 */
function CopyLinkButton({ url, className }: { url: string; className?: string }) {
  const [copied, setCopied] = useState(false)

  async function copy() {
    try {
      await navigator.clipboard.writeText(url)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      toast.error('Could not copy — select the link and copy it manually.')
    }
  }

  return (
    <button
      type="button"
      onClick={() => void copy()}
      className={
        className ??
        'rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary-subtle transition-colors'
      }
    >
      {copied ? 'Copied' : 'Copy link'}
    </button>
  )
}

/** The issued link, shown as soon as the invitation exists. */
function InviteLinkPanel({ invite }: { invite: Invite }) {
  return (
    <div className="space-y-2 rounded-lg border border-border bg-muted/40 p-3">
      <p className="text-sm font-medium text-foreground">
        Invitation created for {invite.email}
      </p>
      <p className="text-xs text-muted-foreground">
        {invite.email_sent
          ? 'The link has been emailed. It expires in 7 days and works once.'
          : invite.email_error
            ? `Not emailed — ${invite.email_error} Send this link yourself; it expires in 7 days and works once.`
            : 'Send this link yourself. It expires in 7 days and works once.'}
      </p>
      <div className="flex items-center gap-2">
        <input
          readOnly
          value={invite.invite_url}
          onFocus={e => e.currentTarget.select()}
          className="w-full rounded border border-border-strong bg-card px-2 py-1.5 font-mono text-xs text-foreground focus:outline-none focus:ring-2 focus:ring-ring"
        />
        <CopyLinkButton
          url={invite.invite_url}
          className="shrink-0 rounded bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground hover:bg-primary-hover"
        />
      </div>
    </div>
  )
}

// ---------- Invite Dialog ----------

interface InviteDialogProps {
  roles: Role[]
  onClose: () => void
  onInvited: () => void
  apiFetch: ReturnType<typeof createClientFetch>
}

function InviteDialog({ roles, onClose, onInvited, apiFetch }: InviteDialogProps) {
  const [email, setEmail] = useState('')
  const [firstName, setFirstName] = useState('')
  const [lastName, setLastName] = useState('')
  const [roleId, setRoleId] = useState<number | null>(null)
  const [sendEmail, setSendEmail] = useState(true)
  const [sending, setSending] = useState(false)
  const [created, setCreated] = useState<Invite | null>(null)

  async function handleSend() {
    if (!email.trim()) return
    setSending(true)
    try {
      const invite = await apiFetch<Invite>('/admin/users/invite', {
        method: 'POST',
        body: JSON.stringify({
          email: email.trim(),
          first_name: firstName || null,
          last_name: lastName || null,
          role_id: roleId,
          send_email: sendEmail,
        }),
      })
      // The dialog switches to the link rather than closing on a toast: an
      // admin with no working SMTP has nothing else to hand over, and the
      // token is what they came for.
      setCreated(invite)
      onInvited()
      if (invite.email_sent) {
        toast.success(`Invitation emailed to ${invite.email}.`)
      } else if (invite.email_error) {
        toast.warning('Invitation created, but the email could not be sent.')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to create the invitation.')
    } finally {
      setSending(false)
    }
  }

  if (created) {
    return (
      <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
        <div className="w-full max-w-md rounded-lg bg-card p-6 shadow-xl space-y-4">
          <h3 className="text-base font-semibold text-foreground">Invitation Created</h3>
          <InviteLinkPanel invite={created} />
          <div className="flex justify-end pt-1">
            <button
              onClick={onClose}
              className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover"
            >
              Done
            </button>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-sm rounded-lg bg-card p-6 shadow-xl space-y-4">
        <h3 className="text-base font-semibold text-foreground">Invite User</h3>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">Email address</label>
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            placeholder="name@company.com"
            className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
          />
        </div>

        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">First name</label>
            <input
              type="text"
              value={firstName}
              onChange={e => setFirstName(e.target.value)}
              placeholder="Jane"
              className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
          <div>
            <label className="block text-sm font-medium text-foreground mb-1">Last name</label>
            <input
              type="text"
              value={lastName}
              onChange={e => setLastName(e.target.value)}
              placeholder="Smith"
              className="w-full rounded border border-border-strong px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
            />
          </div>
        </div>

        <div>
          <label className="block text-sm font-medium text-foreground mb-1">
            Role <span className="font-normal text-muted-foreground">(optional)</span>
          </label>
          <Select
            value={roleId ?? ''}
            onChange={e => setRoleId(e.target.value ? Number(e.target.value) : null)}
          >
            <option value="">No role assigned yet</option>
            {roles.map(r => (
              <option key={r.id} value={r.id}>
                {r.name}
              </option>
            ))}
          </Select>
        </div>

        <div className="flex items-start gap-3">
          <input
            id="invite-send-email"
            type="checkbox"
            checked={sendEmail}
            onChange={e => setSendEmail(e.target.checked)}
            className="mt-0.5 h-4 w-4 rounded border-border-strong text-primary focus:ring-ring"
          />
          <label htmlFor="invite-send-email" className="text-sm text-foreground">
            Email the invitation
            <span className="block text-xs text-muted-foreground">
              The link is shown here either way, ready to copy.
            </span>
          </label>
        </div>

        <div className="flex justify-end gap-2 pt-2">
          <button
            onClick={onClose}
            className="rounded border px-4 py-2 text-sm hover:bg-accent"
          >
            Cancel
          </button>
          <button
            onClick={handleSend}
            disabled={sending || !email.trim()}
            className="rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          >
            {sending ? 'Creating…' : sendEmail ? 'Send Invitation' : 'Create Link'}
          </button>
        </div>
      </div>
    </div>
  )
}

// ---------- Main component ----------

export function UsersClient({ initialUsers, initialTotal, roles }: UsersClientProps) {
  const { data: session } = useSession()
  const [users, setUsers] = useState<User[]>(initialUsers)
  const [total, setTotal] = useState(initialTotal)
  const [page, setPage] = useState(1)
  const [pageLoading, setPageLoading] = useState(false)
  const [editingUser, setEditingUser] = useState<User | null>(null)
  const [resetPasswordUser, setResetPasswordUser] = useState<User | null>(null)
  const [deleteUser, setDeleteUser] = useState<User | null>(null)
  const [showInvite, setShowInvite] = useState(false)
  const [showCreate, setShowCreate] = useState(false)
  const [invites, setInvites] = useState<Invite[]>([])
  const [invitesLoading, setInvitesLoading] = useState(true)
  const [resendingId, setResendingId] = useState<number | null>(null)

  const apiFetch = createClientFetch(session?.user?.access_token)

  const loadInvites = useCallback(async () => {
    setInvitesLoading(true)
    try {
      const data = await apiFetch<Invite[]>('/admin/invites')
      setInvites(data)
    } catch {
      toast.error('Failed to load invitations.')
    } finally {
      setInvitesLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  useEffect(() => {
    void loadInvites()
  }, [loadInvites])

  const loadPage = useCallback(
    async (p: number) => {
      setPageLoading(true)
      try {
        const data = await apiFetch<PaginatedUsers>('/admin/users', {
          searchParams: { page: p, page_size: 25 },
        })
        setUsers(data.items)
        setTotal(data.total)
        setPage(p)
      } catch {
        toast.error('Failed to load users.')
      } finally {
        setPageLoading(false)
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [session?.user?.access_token],
  )

  function handleSaved(updated: User) {
    setUsers(prev => prev.map(u => (u.id === updated.id ? updated : u)))
  }

  async function handleRevokeInvite(invite: Invite) {
    if (!confirm(`Revoke the invitation to ${invite.email}? Their link will stop working.`)) return
    try {
      await apiFetch(`/admin/invites/${invite.id}`, { method: 'DELETE' })
      setInvites(prev => prev.filter(i => i.id !== invite.id))
      toast.success(`Invitation to ${invite.email} revoked.`)
    } catch {
      toast.error('Failed to revoke invitation.')
    }
  }

  async function handleResendInvite(invite: Invite) {
    setResendingId(invite.id)
    try {
      // Resending mints a new token, so the row must be replaced rather than
      // left showing the link that has just stopped working.
      const updated = await apiFetch<Invite>(`/admin/invites/${invite.id}/resend`, {
        method: 'POST',
      })
      setInvites(prev => prev.map(i => (i.id === updated.id ? updated : i)))
      if (updated.email_sent) {
        toast.success(`Invitation re-sent to ${updated.email}.`)
      } else {
        toast.warning('New link issued, but the email could not be sent. Copy the link instead.')
      }
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to resend the invitation.')
    } finally {
      setResendingId(null)
    }
  }

  async function handleResetTotp(user: User) {
    if (!confirm(`Reset 2FA for ${user.email}? They will need to set up a new authenticator app to re-enable it.`)) return
    try {
      await apiFetch(`/admin/users/${user.id}/reset-totp`, { method: 'POST' })
      setUsers(prev => prev.map(u => (u.id === user.id ? { ...u, totp_enabled: false } : u)))
      toast.success(`Two-factor authentication reset for ${user.email}.`)
    } catch {
      toast.error('Failed to reset two-factor authentication.')
    }
  }

  async function handleActivate(user: User) {
    try {
      const updated = await apiFetch<User>(`/admin/users/${user.id}`, {
        method: 'PUT',
        body: JSON.stringify({ is_active: true }),
      })
      setUsers(prev => prev.map(u => (u.id === user.id ? { ...u, is_active: updated.is_active } : u)))
      toast.success(`${user.email} activated.`)
    } catch {
      toast.error('Failed to activate user.')
    }
  }

  const totalPages = Math.ceil(total / 25)

  return (
    <>
      {editingUser && (
        <EditModal
          user={editingUser}
          roles={roles}
          onClose={() => setEditingUser(null)}
          onSaved={handleSaved}
          apiFetch={apiFetch}
        />
      )}
      {resetPasswordUser && (
        <ResetPasswordDialog
          user={resetPasswordUser}
          onClose={() => setResetPasswordUser(null)}
          apiFetch={apiFetch}
        />
      )}
      {deleteUser && (
        <DeleteUserDialog
          user={deleteUser}
          onClose={() => setDeleteUser(null)}
          onDeleted={() => setUsers(prev => prev.map(u => u.id === deleteUser.id ? { ...u, is_active: false } : u))}
          apiFetch={apiFetch}
        />
      )}
      {showCreate && (
        <CreateUserDialog
          roles={roles}
          onClose={() => setShowCreate(false)}
          onCreated={() => void loadPage(1)}
          apiFetch={apiFetch}
        />
      )}
      {showInvite && (
        <InviteDialog
          roles={roles}
          onClose={() => setShowInvite(false)}
          onInvited={() => { void loadPage(1); void loadInvites() }}
          apiFetch={apiFetch}
        />
      )}

      <div>
        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h1 className="text-2xl font-semibold text-foreground">Users</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {total} user{total === 1 ? '' : 's'} in your organisation
            </p>
          </div>
          <div className="flex gap-2">
            <button
              onClick={() => setShowCreate(true)}
              className="inline-flex items-center rounded-lg border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-accent"
            >
              Create User
            </button>
            <button
              onClick={() => setShowInvite(true)}
              className="inline-flex items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground transition-colors hover:bg-primary-hover"
            >
              Invite User
            </button>
          </div>
        </div>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-border text-sm">
              <thead className="bg-muted">
                <tr>
                  {['Email', 'Name', 'Roles', 'Status', 'MFA', 'Last login', ''].map(h => (
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
              <tbody className={`divide-y divide-border ${pageLoading ? 'opacity-50' : ''}`}>
                {users.length === 0 ? (
                  <tr>
                    <td colSpan={7} className="px-4 py-10 text-center text-sm text-muted-foreground">
                      No users found.
                    </td>
                  </tr>
                ) : (
                  users.map(user => (
                    <tr key={user.id} className="transition-colors hover:bg-accent">
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <Avatar
                            name={displayName(user)}
                            email={user.email}
                            avatarUrl={user.avatar_url}
                            size="md"
                          />
                          <div className="min-w-0">
                            <p className="truncate font-medium text-foreground">{user.email}</p>
                            {user.job_title && (
                              <p className="truncate text-xs text-muted-foreground">{user.job_title}</p>
                            )}
                          </div>
                        </div>
                      </td>
                      <td className="px-4 py-3 text-foreground">{displayName(user)}</td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap gap-1">
                          {user.roles.length === 0 ? (
                            <span className="text-muted-foreground text-xs">No roles</span>
                          ) : (
                            user.roles.map(r => <RoleBadge key={r} role={r} />)
                          )}
                        </div>
                      </td>
                      <td className="px-4 py-3">
                        <span
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
 user.is_active
 ? 'bg-success-subtle text-success-strong'
 : 'bg-muted text-muted-foreground'
 }`}
                        >
                          {user.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {user.totp_enabled ? (
                          <span className="inline-flex items-center rounded-full bg-success-subtle px-2 py-0.5 text-xs font-medium text-success-strong">
                            On
                          </span>
                        ) : (
                          <span className="text-xs text-muted-foreground">Off</span>
                        )}
                      </td>
                      <td className="px-4 py-3 text-muted-foreground">
                        {formatDate(user.last_login_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center justify-end gap-1 flex-wrap">
                          <button
                            onClick={() => setEditingUser(user)}
                            className="rounded px-2 py-1 text-xs font-medium text-primary hover:bg-primary-subtle transition-colors"
                          >
                            Edit
                          </button>
                          <button
                            onClick={() => setResetPasswordUser(user)}
                            className="rounded px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors"
                          >
                            Reset PW
                          </button>
                          {user.totp_enabled && (
                            <button
                              onClick={() => void handleResetTotp(user)}
                              className="rounded px-2 py-1 text-xs font-medium text-warning-strong hover:bg-amber-50 transition-colors"
                            >
                              Reset 2FA
                            </button>
                          )}
                          {user.is_active ? (
                            <button
                              onClick={() => setDeleteUser(user)}
                              className="rounded px-2 py-1 text-xs font-medium text-destructive-strong hover:bg-destructive-subtle transition-colors"
                            >
                              Delete
                            </button>
                          ) : (
                            <button
                              onClick={() => void handleActivate(user)}
                              className="rounded px-2 py-1 text-xs font-medium text-success-strong hover:bg-success-subtle transition-colors"
                            >
                              Activate
                            </button>
                          )}
                        </div>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {/* Pagination */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between border-t border-border px-4 py-3">
              <p className="text-xs text-muted-foreground">
                Page {page} of {totalPages} &mdash; {total} users
              </p>
              <div className="flex gap-2">
                <button
                  onClick={() => void loadPage(page - 1)}
                  disabled={page <= 1 || pageLoading}
                  className="rounded border px-3 py-1 text-xs disabled:opacity-40 hover:bg-accent"
                >
                  Previous
                </button>
                <button
                  onClick={() => void loadPage(page + 1)}
                  disabled={page >= totalPages || pageLoading}
                  className="rounded border px-3 py-1 text-xs disabled:opacity-40 hover:bg-accent"
                >
                  Next
                </button>
              </div>
            </div>
          )}
        </div>

        {/* Invitations */}
        <div className="mt-8">
          <h2 className="text-base font-semibold text-foreground mb-3">Invitations</h2>
          <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
            {invitesLoading ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">Loading…</div>
            ) : invites.length === 0 ? (
              <div className="px-4 py-8 text-center text-sm text-muted-foreground">No invitations sent yet.</div>
            ) : (
              <div className="overflow-x-auto">
                <table className="min-w-full divide-y divide-border text-sm">
                  <thead className="bg-muted">
                    <tr>
                      {['Email', 'Role', 'Status', 'Invited', 'Expires', ''].map(h => (
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
                    {invites.map(invite => (
                      <tr key={invite.id} className="hover:bg-accent transition-colors">
                        <td className="px-4 py-3 font-medium text-foreground">{invite.email}</td>
                        <td className="px-4 py-3 text-muted-foreground">{invite.role_name ?? '—'}</td>
                        <td className="px-4 py-3">
                          <InviteStatusBadge status={invite.status} />
                        </td>
                        <td className="px-4 py-3 text-muted-foreground">{formatDate(invite.created_at)}</td>
                        <td className="px-4 py-3 text-muted-foreground">
                          {invite.status === 'accepted' ? '—' : formatDate(invite.expires_at)}
                        </td>
                        <td className="px-4 py-3">
                          <div className="flex items-center justify-end gap-1 flex-wrap">
                            {invite.status === 'pending' && <CopyLinkButton url={invite.invite_url} />}
                            {invite.status !== 'accepted' && (
                              <>
                                <button
                                  onClick={() => void handleResendInvite(invite)}
                                  disabled={resendingId === invite.id}
                                  className="rounded px-2 py-1 text-xs font-medium text-muted-foreground hover:bg-accent transition-colors disabled:opacity-50"
                                >
                                  {resendingId === invite.id ? 'Sending…' : 'Resend'}
                                </button>
                                <button
                                  onClick={() => void handleRevokeInvite(invite)}
                                  className="rounded px-2.5 py-1 text-xs font-medium text-destructive-strong hover:bg-destructive-subtle transition-colors"
                                >
                                  Revoke
                                </button>
                              </>
                            )}
                          </div>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        </div>
      </div>
    </>
  )
}
