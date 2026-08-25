import Link from 'next/link'
import { FileQuestion } from 'lucide-react'
import { buttonVariants } from '@/components/ui/Button'
import { EmptyState } from '@/components/ui/EmptyState'

export const metadata = {
  title: 'Page not found',
}

export default function NotFound() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background p-6">
      <EmptyState
        icon={FileQuestion}
        title="Page not found"
        description="This page does not exist, or the feature it belongs to is turned off for your organisation."
        className="max-w-lg border-solid bg-card"
        action={
          <Link href="/home" className={buttonVariants({ variant: 'primary' })}>
            Go to Home
          </Link>
        }
      />
    </div>
  )
}
