/**
 * Sec Dash brand lockup.
 *
 * The app icon (`/android-chrome-512x512.png`) carries no text, so it is the
 * mark; the product name is rendered as styled text beside it. That keeps the
 * lockup crisp at any size, lets it respond to the theme, and avoids shipping a
 * raster wordmark.
 *
 * An organisation may supply its own `logoUrl` via org settings — white-labelled
 * deployments then show the client's mark and name in place of SecDash. The
 * mark lives in `BrandLogo` because falling back to the app icon on a broken
 * org logo needs `onError`, and so a client component.
 */
import { cn } from '@/lib/utils'
import { BrandLogo } from './BrandLogo'

/** Product name. Import this instead of writing the string inline. */
export const APP_NAME = 'SecDash'

const SIZES = {
  sm: { box: 'h-6 w-6', px: 24, text: 'text-sm' },
  md: { box: 'h-8 w-8', px: 32, text: 'text-base' },
  lg: { box: 'h-12 w-12', px: 48, text: 'text-2xl' },
} as const

interface BrandProps {
  /** Org display name; falls back to "Sec Dash". */
  name?: string | null
  /** Org logo URL; falls back to the Sec Dash app icon. */
  logoUrl?: string | null
  size?: keyof typeof SIZES
  /** Render the mark only — for collapsed sidebars and tight headers. */
  markOnly?: boolean
  className?: string
}

export function Brand({ name, logoUrl, size = 'md', markOnly, className }: BrandProps) {
  const { box, px, text } = SIZES[size]
  const label = name?.trim() || APP_NAME
  const isDefaultBrand = label === APP_NAME

  return (
    <span className={cn('flex items-center gap-2', className)}>
      <BrandLogo logoUrl={logoUrl} box={box} px={px} />
      {!markOnly && (
        <span className={cn('truncate font-semibold tracking-tight text-foreground', text)}>
          {isDefaultBrand ? (
            <>
              SecDash
            </>
          ) : (
            label
          )}
        </span>
      )}
      {/* The visible mark is aria-hidden, so the accessible name lives here. */}
      <span className="sr-only">{label}</span>
    </span>
  )
}
