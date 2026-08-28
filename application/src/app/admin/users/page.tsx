/**
 * User management admin page.
 *
 * Fetches the first page of users and the full roles list server-side so
 * the table renders without a loading flash. Subsequent pagination and all
 * mutations are handled client-side by UsersClient.
 */
import { apiFetch } from '@/lib/api'
import { UsersClient } from '@/components/admin/UsersClient'

export const metadata = {
  title: 'Users',
}

interface User {
  id: number
  email: string
  display_name: string | null
  first_name: string | null
  last_name: string | null
  phone_number: string | null
  is_active: boolean
  totp_enabled: boolean
  last_login_at: string | null
  created_at: string
  roles: string[]
}

interface UsersResponse {
  items: User[]
  total: number
  page: number
  page_size: number
}

interface Role {
  id: number
  name: string
  description: string | null
  is_system: boolean
}

async function getUsers(): Promise<UsersResponse> {
  try {
    return await apiFetch<UsersResponse>('/admin/users', {
      searchParams: { page: 1, page_size: 25 },
    })
  } catch {
    return { items: [], total: 0, page: 1, page_size: 25 }
  }
}

async function getRoles(): Promise<Role[]> {
  try {
    return await apiFetch<Role[]>('/admin/roles')
  } catch {
    return []
  }
}

export default async function UsersPage() {
  const [usersData, roles] = await Promise.all([getUsers(), getRoles()])

  return (
    <UsersClient
      initialUsers={usersData.items}
      initialTotal={usersData.total}
      roles={roles}
    />
  )
}
