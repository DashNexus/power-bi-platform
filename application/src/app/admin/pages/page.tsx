'use client'

/**
 * Admin page list for managing custom HTML pages.
 *
 * Displays all pages with role, publication status, tags, and home page
 * designation. Admins can set any published page as the organisation home.
 */
import { useState, useEffect, useCallback } from 'react'
import Link from 'next/link'
import { useSession } from 'next-auth/react'
import { toast } from 'sonner'
import { Home, Plus } from 'lucide-react'
import { createClientFetch } from '@/lib/api'

interface PageData {
  id: number
  title: string
  slug: string
  is_published: boolean
  is_home_page: boolean
  tags: string[]
  created_at: string
  updated_at: string
}

export default function AdminPagesPage() {
  const { data: session } = useSession()
  const [pages, setPages] = useState<PageData[]>([])
  const [loading, setLoading] = useState(true)
  const apiFetch = createClientFetch(session?.user?.access_token)

  const loadPages = useCallback(async () => {
    if (!session?.user?.access_token) return
    try {
      const data = await apiFetch<PageData[]>('/admin/pages')
      setPages(data)
    } catch {
      toast.error('Failed to load pages.')
    } finally {
      setLoading(false)
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [session?.user?.access_token])

  useEffect(() => {
    void loadPages()
  }, [loadPages])

  if (loading) {
    return (
      <div className="flex h-64 items-center justify-center text-sm text-muted-foreground">
        Loading pages…
      </div>
    )
  }

  return (
    <div>
      <div className="mb-6 flex items-start justify-between">
        <div>
          <h1 className="text-2xl font-semibold text-foreground">Custom Pages</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            {pages.length} page{pages.length === 1 ? '' : 's'} in your organisation
          </p>
        </div>
        <Link
          href="/admin/pages/new"
          className="inline-flex items-center gap-2 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:bg-primary-hover transition-colors"
        >
          <Plus className="h-4 w-4" />
          New Page
        </Link>
      </div>

      <div className="overflow-hidden rounded-xl border border-border bg-card shadow-sm">
        <div className="overflow-x-auto">
          <table className="min-w-full divide-y divide-border text-sm">
            <thead className="bg-muted">
              <tr>
                {['Title', 'Slug', 'Tags', 'Published', 'Last modified', 'Actions'].map(
                  header => (
                    <th
                      key={header}
                      scope="col"
                      className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-muted-foreground"
                    >
                      {header}
                    </th>
                  ),
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {pages.length === 0 ? (
                <tr>
                  <td colSpan={6} className="px-4 py-10 text-center text-sm text-muted-foreground">
                    No pages configured yet. Create a new page to get started.
                  </td>
                </tr>
              ) : (
                pages.map(page => (
                  <tr key={page.id} className="hover:bg-accent transition-colors duration-100">
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <span className="font-medium text-foreground">{page.title}</span>
                        {page.is_home_page && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-warning-subtle px-2 py-0.5 text-xs font-medium text-warning-strong">
                            <Home className="h-3 w-3" />
                            Home
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <code className="rounded bg-muted px-1.5 py-0.5 text-xs text-foreground">
                        {page.slug}
                      </code>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap gap-1">
                        {page.tags && page.tags.length > 0 ? (
                          page.tags.map(tag => (
                            <span
                              key={tag}
                              className="inline-flex items-center rounded-full bg-muted px-2 py-0.5 text-xs text-muted-foreground"
                            >
                              {tag}
                            </span>
                          ))
                        ) : (
                          <span className="text-xs text-muted-foreground">—</span>
                        )}
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${page.is_published ? 'bg-success-subtle text-success-strong' : 'bg-warning-subtle text-warning-strong'}`}
                      >
                        {page.is_published ? 'Published' : 'Draft'}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-muted-foreground">
                      {new Date(page.updated_at).toLocaleDateString('en-US', {
                        year: 'numeric',
                        month: 'short',
                        day: 'numeric',
                      })}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <Link
                          href={`/admin/pages/${page.id}`}
                          className="text-primary hover:text-primary text-xs font-medium"
                        >
                          Edit
                        </Link>
                        <Link
                          href={`/pages/${page.slug}`}
                          target="_blank"
                          className="text-muted-foreground hover:text-foreground text-xs font-medium"
                        >
                          View
                        </Link>
                      </div>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  )
}
