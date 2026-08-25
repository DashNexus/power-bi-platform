'use client'

/**
 * Standard role-based sharing dialog used for every shareable resource
 * (dashboards, ERDs, data dictionaries, custom pages, timelines, apps).
 *
 * Grants are role-only: pick which roles can access (view) the resource. Whether
 * a role can edit is controlled by that role's permissions, not here. Loads and
 * saves `{ role_ids }` at `permissionsPath`.
 */
import { useState, useEffect } from 'react'
import { toast } from 'sonner'
import { X, Loader2, Search, Save } from 'lucide-react'
import type { createClientFetch } from '@/lib/api'

interface RoleOption {
  id: number
  name: string
}

interface ShareResourceDialogProps {
  /** Resource kind shown in the title, e.g. "Dashboard", "ERD", "Timeline". */
  resourceLabel: string
  /** Name of the specific resource being shared. */
  resourceName: string
  /** API path for the resource's permissions, e.g. `/admin/dashboards/5/permissions`. */
  permissionsPath: string
  apiFetch: ReturnType<typeof createClientFetch>
  onClose: () => void
}

export function ShareResourceDialog({
  resourceLabel,
  resourceName,
  permissionsPath,
  apiFetch,
  onClose,
}: ShareResourceDialogProps) {
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [allRoles, setAllRoles] = useState<RoleOption[]>([])
  const [selectedRoleIds, setSelectedRoleIds] = useState<number[]>([])
  const [roleSearch, setRoleSearch] = useState('')

  useEffect(() => {
    async function load() {
      setLoading(true)
      try {
        const [perms, roles] = await Promise.all([
          apiFetch<{ role_ids: number[] }>(permissionsPath),
          apiFetch<RoleOption[]>('/admin/roles'),
        ])
        setSelectedRoleIds(perms.role_ids ?? [])
        setAllRoles(roles)
      } catch {
        toast.error('Failed to load permissions.')
      } finally {
        setLoading(false)
      }
    }
    void load()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [permissionsPath])

  function toggleRole(id: number) {
    setSelectedRoleIds(prev => (prev.includes(id) ? prev.filter(r => r !== id) : [...prev, id]))
  }

  async function handleSave() {
    setSaving(true)
    try {
      // Send user_ids: [] for parity with resources that accept both — extra
      // keys are ignored by role-only endpoints.
      await apiFetch(permissionsPath, {
        method: 'PUT',
        body: JSON.stringify({ role_ids: selectedRoleIds, user_ids: [] }),
      })
      toast.success('Access updated.')
      onClose()
    } catch {
      toast.error('Failed to update access.')
    } finally {
      setSaving(false)
    }
  }

  const filteredRoles = allRoles.filter(r =>
    r.name.toLowerCase().includes(roleSearch.toLowerCase()),
  )

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="w-full max-w-md rounded-lg bg-card shadow-xl overflow-hidden">
        <div className="flex items-center justify-between px-6 pt-5 pb-4 border-b">
          <div>
            <h3 className="text-base font-semibold text-foreground">Share {resourceLabel}</h3>
            <p className="text-xs text-muted-foreground mt-0.5 truncate max-w-xs">{resourceName}</p>
          </div>
          <button type="button" onClick={onClose} className="text-muted-foreground hover:text-foreground">
            <X className="h-5 w-5" />
          </button>
        </div>

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : (
          <div className="p-6 space-y-4">
            <p className="rounded-md bg-primary-subtle px-3 py-2.5 text-xs text-info-strong leading-relaxed">
              Select which roles can access this {resourceLabel.toLowerCase()}. With no roles
              selected, every role with the feature&apos;s view permission can see it. Editing is
              controlled by the role&apos;s permissions.
            </p>

            <div className="flex items-center rounded border border-border-strong px-2 py-1.5 gap-1.5">
              <Search className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
              <input
                value={roleSearch}
                onChange={e => setRoleSearch(e.target.value)}
                placeholder="Search roles…"
                className="flex-1 text-sm outline-none bg-transparent"
              />
            </div>

            <div className="max-h-72 overflow-y-auto space-y-1">
              {filteredRoles.length === 0 ? (
                <p className="py-6 text-center text-xs text-muted-foreground">No roles found.</p>
              ) : (
                filteredRoles.map(role => (
                  <label
                    key={role.id}
                    className="flex items-center gap-2 rounded px-2 py-1.5 hover:bg-accent cursor-pointer"
                  >
                    <input
                      type="checkbox"
                      checked={selectedRoleIds.includes(role.id)}
                      onChange={() => toggleRole(role.id)}
                      className="h-4 w-4 rounded border-border-strong text-primary focus:ring-ring"
                    />
                    <span className="text-sm text-foreground">{role.name}</span>
                  </label>
                ))
              )}
            </div>
          </div>
        )}

        <div className="flex justify-end gap-2 px-6 py-4 border-t bg-muted">
          <button
            type="button"
            onClick={onClose}
            disabled={saving}
            className="rounded border px-4 py-2 text-sm hover:bg-card disabled:opacity-50"
          >
            Cancel
          </button>
          <button
            type="button"
            onClick={() => void handleSave()}
            disabled={saving || loading}
            className="inline-flex items-center gap-2 rounded bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover disabled:opacity-50"
          >
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Save className="h-4 w-4" />}
            {saving ? 'Saving…' : 'Save'}
          </button>
        </div>
      </div>
    </div>
  )
}
