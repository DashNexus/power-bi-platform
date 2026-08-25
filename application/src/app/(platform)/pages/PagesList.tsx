'use client'

/**
 * Client half of the custom-pages listing.
 *
 * The page is a Server Component; search and the card/list toggle need client
 * state, so the list itself lives here.
 */
import { FileText } from 'lucide-react'
import { Card, EmptyState } from '@/components/ui'
import { ResourceBrowser, type ResourceItem } from '@/components/portal/ResourceBrowser'

export interface PageSummary {
  id: number
  title: string
  slug: string
  required_role: string
  updated_at: string
}

function formatUpdated(iso: string): string {
  return new Date(iso).toLocaleDateString('en-US', {
    year: 'numeric',
    month: 'short',
    day: 'numeric',
  })
}

export function PagesList({ pages }: { pages: PageSummary[] }) {
  const items: ResourceItem[] = pages.map(page => ({
    key: page.id,
    href: `/pages/${page.slug}`,
    icon: FileText,
    title: page.title,
    description: `Updated ${formatUpdated(page.updated_at)}`,
    badge: { label: 'Page', tone: 'info' },
    // The slug is how people refer to a page in links, so make it findable.
    searchText: page.slug,
  }))

  return (
    <ResourceBrowser
      items={items}
      storageKey="pages"
      searchPlaceholder="Search pages…"
      nameColumnLabel="Page"
      gridClassName="grid gap-4 sm:grid-cols-2 lg:grid-cols-3"
      emptyState={
        <Card className="p-6">
          <EmptyState
            icon={FileText}
            title="No pages published yet"
            description="Custom pages are rich HTML pages your organisation publishes into the portal — runbooks, policies, onboarding guides. Admins can create one under Admin → Pages."
          />
        </Card>
      }
    />
  )
}
