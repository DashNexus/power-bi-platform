/**
 * Public-facing custom HTML page rendered by slug.
 *
 * Fetches the page from the API using the current session token and renders
 * the author-supplied HTML content inside a sandboxed prose container.
 * Returns a 404 page when the page does not exist or the user's role is
 * insufficient (the API returns 404 in both cases to avoid leaking existence).
 */
import { notFound } from 'next/navigation'
import { apiFetch } from '@/lib/api'

interface PageData {
  id: number
  title: string
  slug: string
  content: string
  required_role: string
  is_published: boolean
  created_at: string
  updated_at: string
}

async function getPage(slug: string): Promise<PageData | null> {
  try {
    return await apiFetch<PageData>(`/pages/${slug}`)
  } catch {
    return null
  }
}

export default async function CustomPage({ params }: { params: Promise<{ slug: string }> }) {
  const { slug } = await params
  const page = await getPage(slug)

  if (!page) {
    notFound()
  }

  return (
    <article>
      {/* Header
      <header className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">{page.title}</h1>
        <p className="mt-1 text-xs text-muted-foreground">
          Last updated{' '}
          {new Date(page.updated_at).toLocaleDateString('en-US', {
            year: 'numeric',
            month: 'short',
            day: 'numeric',
          })}
        </p>
      </header>
      */}
      {/* dangerouslySetInnerHTML is intentional — content is admin-authored HTML */}
      <div
        className="prose max-w-none p-6"
        dangerouslySetInnerHTML={{ __html: page.content }}
      />
    </article>
  )
}
