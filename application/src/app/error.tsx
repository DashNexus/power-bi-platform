'use client'

/**
 * Route-level error boundary.
 *
 * Without this file an uncaught render error in any route shows the bare Next.js
 * error screen in production. `reset()` re-renders the segment, which recovers
 * from transient failures (an API blip) without a full reload.
 */
import { useEffect } from 'react'
import { RotateCcw } from 'lucide-react'
import { Button } from '@/components/ui/Button'
import { ErrorState } from '@/components/ui/EmptyState'

export default function RouteError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    // Surfaces in the server logs / browser console with the digest that
    // correlates to the server-side stack trace.
    console.error('Route error', { digest: error.digest, message: error.message })
  }, [error])

  return (
    <div className="flex flex-1 items-center justify-center p-6">
      <ErrorState
        title="This page could not be loaded"
        description="An unexpected error occurred while rendering. Try again — if it keeps happening, contact your administrator."
        className="max-w-lg"
        action={
          <div className="flex items-center gap-2">
            <Button onClick={reset}>
              <RotateCcw aria-hidden />
              Try Again
            </Button>
            {error.digest && (
              <code className="rounded bg-muted px-2 py-1 text-xs text-muted-foreground">
                {error.digest}
              </code>
            )}
          </div>
        }
      />
    </div>
  )
}
