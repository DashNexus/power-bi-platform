'use client'

/**
 * Role editor page — create or edit a single role.
 *
 * When the route param is "new", renders a blank create form that POSTs to
 * /admin/roles. For existing roles it fetches the current state and PUTs
 * the updated data. System roles are read-only: the permission matrix is
 * visible but no save action is available.
 */
import { useState, useEffect } from 'react'
import { useParams, useRouter } from 'next/navigation'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { createClientFetch } from '@/lib/api'
import { PermissionMatrix, type Permission } from '@/components/admin/PermissionMatrix'
import { cn } from '@/lib/utils'

interface RoleDetail {
  id: number
  name: string
  description: string | null
  is_system: boolean
  permissions: string[]
}

export default function RoleEditorPage() {
  const { id } = useParams<{ id: string }>()
  const isNew = id === 'new'
  const router = useRouter()
  const { data: session } = useSession()
  const apiFetch = createClientFetch(session?.user?.access_token)

  const [role, setRole] = useState<RoleDetail | null>(null)
  const [allPermissions, setAllPermissions] = useState<Permission[]>([])
  const [name, setName] = useState('')
  const [description, setDescription] = useState('')
  const [assigned, setAssigned] = useState<string[]>([])
  const [isSaving, setIsSaving] = useState(false)
  const [isLoading, setIsLoading] = useState(!isNew)

  useEffect(() => {
    if (!session) return

    async function loadPermissions() {
      try {
        const permsData = await apiFetch<Permission[]>('/admin/permissions')
        setAllPermissions(permsData)
      } catch {
        // Permissions catalogue unavailable — PermissionMatrix shows empty state
      }
    }

    if (isNew) {
      // Creating a new role — only load the permissions catalogue
      loadPermissions()
      return
    }

    async function loadExisting() {
      try {
        const [roleData, permsData] = await Promise.all([
          apiFetch<RoleDetail>(`/admin/roles/${id}`),
          apiFetch<Permission[]>('/admin/permissions'),
        ])
        setRole(roleData)
        setName(roleData.name)
        setDescription(roleData.description ?? '')
        setAssigned(roleData.permissions)
        setAllPermissions(permsData)
      } catch {
        toast.error('Failed to load role.')
        router.push('/admin/roles')
      } finally {
        setIsLoading(false)
      }
    }

    loadExisting()
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [id, session, isNew])

  async function handleSave() {
    if (!name.trim()) {
      toast.error('Role name is required.')
      return
    }

    setIsSaving(true)
    try {
      const body = JSON.stringify({
        name: name.trim(),
        description: description.trim() || null,
        permission_keys: assigned,
      })

      if (isNew) {
        await apiFetch('/admin/roles', { method: 'POST', body })
        toast.success('Role created.')
      } else {
        await apiFetch(`/admin/roles/${id}`, { method: 'PUT', body })
        toast.success('Role updated.')
      }

      // No separate visibility step: GET /portal/features derives what a role
      // can see from the permissions saved above, so assigning a permission is
      // the whole of granting access to its feature.
      router.push('/admin/roles')
    } catch (err) {
      const msg = err instanceof Error ? err.message : 'Unknown error'
      toast.error(`Failed to save role: ${msg}`)
    } finally {
      setIsSaving(false)
    }
  }

  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Loading...
      </div>
    )
  }

  const isSystemRole = role?.is_system ?? false
  const isReadOnly = isSystemRole

  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">
          {isNew ? 'Create Role' : 'Edit Role'}
        </h1>
        {isSystemRole && (
          <p className="mt-1 text-sm text-warning-strong">
            This is a system role and cannot be modified.
          </p>
        )}
      </div>

      <div className="space-y-6">
        {/* Name */}
        <div>
          <label htmlFor="role-name" className="block text-sm font-medium text-foreground">
            Role name
          </label>
          <input
            id="role-name"
            type="text"
            value={name}
            onChange={e => setName(e.target.value)}
            disabled={isReadOnly}
            placeholder="e.g. regional-manager"
            className={cn(
              'mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm',
              'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
              isReadOnly
                ? 'border-border bg-muted text-muted-foreground cursor-not-allowed'
                : 'border-border-strong bg-card',
            )}
          />
        </div>

        {/* Description */}
        <div>
          <label htmlFor="role-desc" className="block text-sm font-medium text-foreground">
            Description
          </label>
          <textarea
            id="role-desc"
            rows={2}
            value={description}
            onChange={e => setDescription(e.target.value)}
            disabled={isReadOnly}
            className={cn(
              'mt-1 block w-full rounded-lg border px-3 py-2 text-sm shadow-sm resize-none',
              'focus:outline-none focus:ring-2 focus:ring-ring focus:border-transparent',
              isReadOnly
                ? 'border-border bg-muted text-muted-foreground cursor-not-allowed'
                : 'border-border-strong bg-card',
            )}
          />
        </div>

        {/* Permission matrix */}
        <div>
          <h2 className="mb-3 text-sm font-semibold text-foreground">Permissions</h2>
          <PermissionMatrix
            permissions={allPermissions}
            assigned={assigned}
            onChange={isReadOnly ? () => {} : setAssigned}
          />
        </div>

        {/* Actions — hidden for system roles */}
        {!isReadOnly && (
          <div className="flex items-center justify-end gap-3 pt-4 border-t border-border">
            <button
              type="button"
              onClick={() => router.push('/admin/roles')}
              className="rounded-lg border border-border-strong bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent transition-colors"
            >
              Cancel
            </button>
            <button
              type="button"
              onClick={handleSave}
              disabled={isSaving}
              className={cn(
                'rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground',
                'hover:bg-primary-hover transition-colors',
                'disabled:opacity-50 disabled:cursor-not-allowed',
              )}
            >
              {isSaving ? 'Saving...' : isNew ? 'Create Role' : 'Save Role'}
            </button>
          </div>
        )}

        {isReadOnly && (
          <div className="flex justify-end pt-4 border-t border-border">
            <button
              type="button"
              onClick={() => router.push('/admin/roles')}
              className="rounded-lg border border-border-strong bg-card px-4 py-2 text-sm font-medium text-foreground hover:bg-accent transition-colors"
            >
              Back to Roles
            </button>
          </div>
        )}
      </div>
    </div>
  )
}
