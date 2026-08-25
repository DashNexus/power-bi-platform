/**
 * User-facing pages listing.
 *
 * Fetches all published pages the current user is permitted to view; the
 * searchable card/list browser is rendered by the client half in PagesList.
 */
import { apiFetch } from '@/lib/api'
import { PageHeader } from '@/components/ui/PageHeader'
import { PagesList, type PageSummary } from './PagesList'

async function getPages(): Promise<PageSummary[]> {
  try {
    return await apiFetch<PageSummary[]>('/pages')
  } catch {
    return []
  }
}

export default async function PagesIndexPage() {
  const pages = await getPages()

  return (
    <div className="flex flex-col gap-6">
      <PageHeader title="Pages" description="Custom pages published by your organisation." />
      <PagesList pages={pages} />
    </div>
  )
}
