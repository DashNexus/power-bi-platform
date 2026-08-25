'use client'

/**
 * Role management page.
 *
 * Lists all roles with their permissions and type (system vs custom).
 * Custom roles can be edited and deleted; system roles are read-only.
 */
import { useState, useEffect } from 'react'
import Link from 'next/link'
import { Pencil, Trash2 } from 'lucide-react'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { createClientFetch } from '@/lib/api'

interface RoleRecord {
  id: number
  name: string
  description: string | null
  is_system: boolean
  permissions: string[]
}

export default function RolesPage() {
  const { data: session } = useSession()
  const [roles, setRoles] = useState<RoleRecord[]>([])
  const [loading, setLoading] = useState(true)
  const [deletingId, setDeletingId] = useState<number | null>(null)

  const apiFetch = createClientFetch(session?.user?.access_token)

  useEffect(() => {
    if (!session?.user?.access_token) return
    apiFetch<RoleRecord[]>('/admin/roles')
      .then(setRoles)
      .catch(() => toast.error('Failed to load roles.'))
      .finally(() => setLoading(false))
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  async function handleDelete(role: RoleRecord) {
    if (
      !confirm(
        `Delete the "${role.name}" role? This cannot be undone and will remove it from all assigned users.`,
      )
    )
      return
    setDeletingId(role.id)
    try {
      await apiFetch(`/admin/roles/${role.id}`, { method: 'DELETE' })
      setRoles(prev => prev.filter(r => r.id !== role.id))
      toast.success(`Role "${role.name}" deleted.`)
    } catch (err) {
      toast.error(err instanceof Error ? err.message : 'Failed to delete role.')
    } finally {
      setDeletingId(null)
    }
  }

  if (loading) {
    return <div className="py-12 text-center text-sm text-muted-foreground">Loading roles…</div>
  }

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Roles</h1>
          <p className="mt-1 text-sm text-muted-foreground">Manage roles and their permission sets.</p>
        </div>
        <Link
          href="/admin/roles/new"
          className="inline-flex items-center rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover transition-colors"
        >
          Add Role
        </Link>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
        <table className="min-w-full divide-y divide-border text-sm">
          <thead className="bg-muted">
            <tr>
              {['Name', 'Description', 'Permissions', 'Type', ''].map(h => (
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
            {roles.length === 0 ? (
              <tr>
                <td colSpan={5} className="px-4 py-10 text-center text-sm text-muted-foreground">
                  No roles configured.
                </td>
              </tr>
            ) : (
              roles.map(role => (
                <tr key={role.id} className="hover:bg-accent transition-colors">
                  <td className="px-4 py-3 font-medium text-foreground">{role.name}</td>
                  <td className="px-4 py-3 text-muted-foreground">
                    {role.description ?? <span className="text-muted-foreground">—</span>}
                  </td>
                  <td className="px-4 py-3 text-foreground">{role.permissions?.length ?? 0}</td>
                  <td className="px-4 py-3">
                    <span
                      className={
                        role.is_system
                          ? 'inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground'
                          : 'inline-flex items-center rounded-full bg-primary-subtle px-2 py-0.5 text-xs font-medium text-info-strong'
                      }
                    >
                      {role.is_system ? 'System' : 'Custom'}
                    </span>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2 justify-end">
                      <Link
                        href={`/admin/roles/${role.id}`}
                        aria-label={`Edit ${role.name}`}
                        className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
                      >
                        <Pencil className="h-4 w-4" />
                      </Link>
                      {!role.is_system && (
                        <button
                          type="button"
                          aria-label={`Delete ${role.name}`}
                          disabled={deletingId === role.id}
                          onClick={() => void handleDelete(role)}
                          className="rounded-lg p-1.5 text-muted-foreground hover:bg-destructive-subtle hover:text-destructive-strong transition-colors disabled:opacity-40"
                        >
                          <Trash2 className="h-4 w-4" />
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
    </div>
  )
}
