/**
 * Streaming fallback for admin routes, which are mostly header + table.
 */
import { Skeleton } from '@/components/ui/Feedback'

export default function AdminLoading() {
  return (
    <div className="space-y-6" role="status" aria-label="Loading page">
      <div className="space-y-2">
        <Skeleton className="h-8 w-48" />
        <Skeleton className="h-4 w-72" />
      </div>
      <Skeleton className="h-64 w-full rounded-xl" />
    </div>
  )
}
