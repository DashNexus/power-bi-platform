/**
 * Streaming fallback for platform routes.
 *
 * Platform pages are Server Components that await the API, so without a
 * `loading.tsx` navigation appears frozen until the data resolves. The skeleton
 * mirrors the PageHeader + content shape most routes render.
 */
import { Skeleton } from '@/components/ui/Feedback'

export default function PlatformLoading() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading page">
      <div className="space-y-2">
        <Skeleton className="h-8 w-56" />
        <Skeleton className="h-4 w-80" />
      </div>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-32 w-full rounded-xl" />
        ))}
      </div>
    </div>
  )
}
