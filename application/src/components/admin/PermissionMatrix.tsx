'use client'

/**
 * Checkbox grid for assigning permissions to a role.
 *
 * Groups permissions by category. Each row is a permission; the single column
 * is a checkbox toggling that permission on/off for the current role.
 */
import { cn } from '@/lib/utils'

export interface Permission {
  key: string
  description: string
  category: string
}

interface PermissionMatrixProps {
  permissions: Permission[]
  assigned: string[]
  onChange: (keys: string[]) => void
}

export function PermissionMatrix({ permissions, assigned, onChange }: PermissionMatrixProps) {
  const assignedSet = new Set(assigned)

  function toggle(key: string) {
    const next = new Set(assignedSet)
    if (next.has(key)) {
      next.delete(key)
    } else {
      next.add(key)
    }
    onChange(Array.from(next))
  }

  // Group permissions by category
  const grouped = permissions.reduce<Record<string, Permission[]>>((acc, p) => {
    if (!acc[p.category]) acc[p.category] = []
    acc[p.category].push(p)
    return acc
  }, {})

  const categories = Object.keys(grouped).sort()

  if (permissions.length === 0) {
    return (
      <p className="text-sm text-muted-foreground italic">No permissions available.</p>
    )
  }

  return (
    <div className="space-y-6">
      {categories.map(category => (
        <div key={category}>
          <h3 className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted-foreground">
            {category}
          </h3>
          <div className="overflow-hidden rounded-xl border border-border">
            <table className="min-w-full divide-y divide-border text-sm">
              <thead className="bg-muted">
                <tr>
                  <th className="px-4 py-2 text-left text-xs font-medium text-muted-foreground">
                    Permission
                  </th>
                  <th className="w-16 px-4 py-2 text-center text-xs font-medium text-muted-foreground">
                    Granted
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border bg-card">
                {grouped[category].map(p => (
                  <tr
                    key={p.key}
                    className={cn(
                      'transition-colors duration-100',
                      assignedSet.has(p.key) ? 'bg-primary-subtle' : 'hover:bg-accent',
                    )}
                  >
                    <td className="px-4 py-2.5">
                      <label
                        htmlFor={`perm-${p.key}`}
                        className="block cursor-pointer"
                      >
                        <span className="font-medium text-foreground">{p.key}</span>
                        {p.description && (
                          <span className="block text-xs text-muted-foreground">{p.description}</span>
                        )}
                      </label>
                    </td>
                    <td className="w-16 px-4 py-2.5 text-center">
                      <input
                        id={`perm-${p.key}`}
                        type="checkbox"
                        checked={assignedSet.has(p.key)}
                        onChange={() => toggle(p.key)}
                        className={cn(
                          'h-4 w-4 rounded border-border-strong text-primary',
                          'focus:ring-2 focus:ring-ring focus:ring-offset-2',
                          'cursor-pointer',
                        )}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      ))}
    </div>
  )
}
