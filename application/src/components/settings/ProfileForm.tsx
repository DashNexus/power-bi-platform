'use client'

/**
 * Editable profile: avatar, personal details, and password.
 *
 * This page was read-only and told people to "contact your administrator" to
 * change their own display name. Everything here is a field the subject owns.
 * Rates, capacity, skills, and active status are deliberately absent — those are
 * the org's to set, and self-editing a bill rate is the obvious problem.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { Trash2, Upload } from 'lucide-react'
import { createClientFetch } from '@/lib/api'
import { Avatar, Badge, Button, Card, Field, Input, Select } from '@/components/ui'
import { TIMEZONES } from '@/lib/timezones'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/** Mirrors `MyProfileResponse` in `api/app/routers/users.py`. */
export interface MyProfile {
  user_id: number
  email: string
  display_name: string | null
  first_name: string | null
  last_name: string | null
  job_title: string | null
  department: string | null
  phone_number: string | null
  timezone: string | null
  avatar_url: string | null
  role: string
  roles: string[]
  totp_enabled: boolean
  has_password: boolean
}

/** The fields this form owns — see `ProfileUpdate` in `api/app/routers/users.py`. */
type EditableField =
  | 'display_name'
  | 'first_name'
  | 'last_name'
  | 'job_title'
  | 'department'
  | 'phone_number'
  | 'timezone'

const MIN_PASSWORD_LENGTH = 12

export function ProfileForm() {
  const { data: session, update: updateSession } = useSession()
  const token = session?.user?.access_token
  const apiFetch = useMemo(() => createClientFetch(token), [token])

  const [profile, setProfile] = useState<MyProfile | null>(null)
  const [fields, setFields] = useState<Record<EditableField, string>>({
    display_name: '',
    first_name: '',
    last_name: '',
    job_title: '',
    department: '',
    phone_number: '',
    timezone: '',
  })
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [changingPassword, setChangingPassword] = useState(false)

  const applyProfile = useCallback((next: MyProfile) => {
    setProfile(next)
    setFields({
      display_name: next.display_name ?? '',
      first_name: next.first_name ?? '',
      last_name: next.last_name ?? '',
      job_title: next.job_title ?? '',
      department: next.department ?? '',
      phone_number: next.phone_number ?? '',
      timezone: next.timezone ?? '',
    })
  }, [])

  useEffect(() => {
    if (!token) return
    apiFetch<MyProfile>('/users/me')
      .then(applyProfile)
      .catch(() => toast.error('Could not load your profile.'))
      .finally(() => setLoading(false))
  }, [apiFetch, applyProfile, token])

  function setField(name: EditableField, value: string) {
    setFields(prev => ({ ...prev, [name]: value }))
  }

  async function save() {
    setSaving(true)
    try {
      // Empty strings are sent as-is; the API treats a blank field as "clear it",
      // which is what an emptied input means.
      const updated = await apiFetch<MyProfile>('/users/me', {
        method: 'PUT',
        body: JSON.stringify(fields),
      })
      applyProfile(updated)
      toast.success('Profile saved.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not save your profile.')
    } finally {
      setSaving(false)
    }
  }

  async function uploadAvatar(file: File) {
    setUploading(true)
    try {
      const form = new FormData()
      form.append('file', file)
      // FormData must not go through apiFetch, which sets a JSON content type.
      const response = await fetch(`${API_BASE}/users/me/avatar`, {
        method: 'POST',
        headers: { Authorization: `Bearer ${token}` },
        body: form,
      })
      if (!response.ok) {
        const detail = await response
          .json()
          .then((p: { detail?: string }) => p.detail)
          .catch(() => null)
        throw new Error(detail || 'Upload failed')
      }
      const { avatar_url } = (await response.json()) as { avatar_url: string }
      setProfile(prev => (prev ? { ...prev, avatar_url } : prev))
      // Without this the navbar keeps the old image until the next sign-in: the
      // avatar lives in the session JWT.
      await updateSession({ avatar_url })
      toast.success('Avatar updated.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not upload that image.')
    } finally {
      setUploading(false)
      if (fileInput.current) fileInput.current.value = ''
    }
  }

  async function removeAvatar() {
    try {
      await apiFetch('/users/me/avatar', { method: 'DELETE' })
      setProfile(prev => (prev ? { ...prev, avatar_url: null } : prev))
      await updateSession({ avatar_url: null })
      toast.success('Avatar removed.')
    } catch {
      toast.error('Could not remove your avatar.')
    }
  }

  async function changePassword() {
    if (newPassword !== confirmPassword) {
      toast.error('The new passwords do not match.')
      return
    }
    setChangingPassword(true)
    try {
      await apiFetch('/users/me/password', {
        method: 'POST',
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      })
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      toast.success('Password changed.')
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Could not change your password.')
    } finally {
      setChangingPassword(false)
    }
  }

  if (loading) {
    return (
      <div className="flex h-48 items-center justify-center text-sm text-muted-foreground">
        Loading your profile…
      </div>
    )
  }

  if (!profile) {
    return <Card className="p-6 text-sm text-muted-foreground">Your profile is unavailable.</Card>
  }

  const passwordTooShort = newPassword.length > 0 && newPassword.length < MIN_PASSWORD_LENGTH
  const passwordsDiffer = confirmPassword.length > 0 && newPassword !== confirmPassword

  return (
    <div className="space-y-6">
      <Card className="space-y-4 p-5">
        <div className="flex items-center gap-4">
          <Avatar
            name={fields.display_name || profile.email}
            email={profile.email}
            avatarUrl={profile.avatar_url}
            size="xl"
          />
          <div className="space-y-2">
            <div className="flex flex-wrap gap-2">
              <Button
                variant="secondary"
                size="sm"
                onClick={() => fileInput.current?.click()}
                isLoading={uploading}
              >
                <Upload aria-hidden />
                {profile.avatar_url ? 'Replace' : 'Upload'}
              </Button>
              {profile.avatar_url && (
                <Button variant="destructive-ghost" size="sm" onClick={() => void removeAvatar()}>
                  <Trash2 aria-hidden />
                  Remove
                </Button>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              PNG, JPEG, GIF, or WebP up to 4 MB. Without one you get your initials.
            </p>
          </div>
          <input
            ref={fileInput}
            type="file"
            accept="image/png,image/jpeg,image/gif,image/webp"
            className="hidden"
            onChange={e => {
              const file = e.target.files?.[0]
              if (file) void uploadAvatar(file)
            }}
          />
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <div className="flex items-center justify-between gap-3">
          <div>
            <h2 className="text-sm font-semibold text-foreground">Details</h2>
            <p className="text-xs text-muted-foreground">{profile.email}</p>
          </div>
          <div className="flex flex-wrap justify-end gap-1">
            {(profile.roles.length > 0 ? profile.roles : [profile.role]).map(role => (
              <Badge key={role} tone="info">
                {role}
              </Badge>
            ))}
          </div>
        </div>

        <div className="grid gap-4 sm:grid-cols-2">
          <Field label="Display name" htmlFor="display_name">
            <Input
              id="display_name"
              value={fields.display_name}
              onChange={e => setField('display_name', e.target.value)}
            />
          </Field>
          <Field label="Job title" htmlFor="job_title">
            <Input
              id="job_title"
              value={fields.job_title}
              onChange={e => setField('job_title', e.target.value)}
              placeholder="Data Analyst"
            />
          </Field>
          <Field label="First name" htmlFor="first_name">
            <Input
              id="first_name"
              value={fields.first_name}
              onChange={e => setField('first_name', e.target.value)}
            />
          </Field>
          <Field label="Last name" htmlFor="last_name">
            <Input
              id="last_name"
              value={fields.last_name}
              onChange={e => setField('last_name', e.target.value)}
            />
          </Field>
          <Field label="Department" htmlFor="department">
            <Input
              id="department"
              value={fields.department}
              onChange={e => setField('department', e.target.value)}
            />
          </Field>
          <Field
            label="Phone"
            htmlFor="phone_number"
            hint="Used for SMS notifications, in +14155550123 form."
          >
            <Input
              id="phone_number"
              value={fields.phone_number}
              onChange={e => setField('phone_number', e.target.value)}
            />
          </Field>
          <Field
            label="Time zone"
            htmlFor="timezone"
            className="sm:col-span-2"
            hint="Used for due dates and logged time."
          >
            <Select
              id="timezone"
              value={fields.timezone}
              onChange={e => setField('timezone', e.target.value)}
            >
              <option value="">Use the organisation default</option>
              {TIMEZONES.map(zone => (
                <option key={zone} value={zone}>
                  {zone.replace(/_/g, ' ')}
                </option>
              ))}
            </Select>
          </Field>
        </div>

        <div className="flex justify-end">
          <Button onClick={() => void save()} isLoading={saving}>
            Save changes
          </Button>
        </div>
      </Card>

      <Card className="space-y-4 p-5">
        <div>
          <h2 className="text-sm font-semibold text-foreground">Password</h2>
          <p className="text-xs text-muted-foreground">
            {profile.has_password
              ? 'Changing your password does not sign you out of other devices.'
              : 'You sign in with an identity provider, so there is no password to change.'}
          </p>
        </div>

        {profile.has_password && (
          <>
            <div className="grid gap-4 sm:grid-cols-3">
              <Field label="Current password" htmlFor="current_password">
                <Input
                  id="current_password"
                  type="password"
                  autoComplete="current-password"
                  value={currentPassword}
                  onChange={e => setCurrentPassword(e.target.value)}
                />
              </Field>
              <Field
                label="New password"
                htmlFor="new_password"
                error={passwordTooShort ? `At least ${MIN_PASSWORD_LENGTH} characters.` : undefined}
              >
                <Input
                  id="new_password"
                  type="password"
                  autoComplete="new-password"
                  invalid={passwordTooShort}
                  value={newPassword}
                  onChange={e => setNewPassword(e.target.value)}
                />
              </Field>
              <Field
                label="Confirm new password"
                htmlFor="confirm_password"
                error={passwordsDiffer ? 'Does not match.' : undefined}
              >
                <Input
                  id="confirm_password"
                  type="password"
                  autoComplete="new-password"
                  invalid={passwordsDiffer}
                  value={confirmPassword}
                  onChange={e => setConfirmPassword(e.target.value)}
                />
              </Field>
            </div>
            <div className="flex justify-end">
              <Button
                variant="secondary"
                onClick={() => void changePassword()}
                isLoading={changingPassword}
                disabled={
                  !currentPassword ||
                  newPassword.length < MIN_PASSWORD_LENGTH ||
                  newPassword !== confirmPassword
                }
              >
                Change password
              </Button>
            </div>
          </>
        )}
      </Card>
    </div>
  )
}
