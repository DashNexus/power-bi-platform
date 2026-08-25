/**
 * Shown when a user navigates to a page they don't have access to.
 *
 * Displayed in-place (not a redirect) so the user understands why the page
 * is empty and who to contact. Feature-specific layouts pass a `feature`
 * label so the message is concrete rather than generic.
 */
import { Lock } from 'lucide-react'

interface AccessDeniedProps {
  feature?: string
}

export function AccessDenied({ feature }: AccessDeniedProps) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] text-center px-4">
      <div className="flex h-16 w-16 items-center justify-center rounded-full bg-muted mb-4">
        <Lock className="h-8 w-8 text-muted-foreground " />
      </div>
      <h2 className="text-lg font-semibold text-foreground ">Access restricted</h2>
      <p className="mt-2 text-sm text-muted-foreground max-w-sm">
        {feature
          ? `You don't have permission to access ${feature}. Contact your administrator if you think this is a mistake.`
          : "You don't have permission to access this page. Contact your administrator if you think this is a mistake."}
      </p>
    </div>
  )
}
