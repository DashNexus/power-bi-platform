'use client'

/**
 * The mark half of the brand lockup: an org's own logo, or the Sec Dash icon.
 *
 * This is a client component only because a fallback needs `onError` — an org
 * `logoUrl` is an arbitrary remote URL that can 404, expire, or be blocked, and
 * a broken image left the lockup as a text-only fragment (or a broken-image
 * glyph, depending on the browser). `Brand` itself stays server-renderable,
 * which keeps `APP_NAME` importable from server metadata.
 */
import { useEffect, useState } from 'react'
import Image from 'next/image'
import { cn } from '@/lib/utils'

/** Bundled app icon — the mark shown when an org has no usable logo of its own. */
export const DEFAULT_LOGO_SRC = '/android-chrome-512x512.png'

interface BrandLogoProps {
  /** Org logo URL; a missing or unloadable one falls back to the app icon. */
  logoUrl?: string | null
  /** Tailwind height/width pair for the current size step. */
  box: string
  /** Pixel size passed to next/image for the bundled icon. */
  px: number
}

export function BrandLogo({ logoUrl, box, px }: BrandLogoProps) {
  const [hasFailed, setHasFailed] = useState(false)

  // A newly saved logo gets its own chance to load; without this, one failure
  // would pin the fallback for as long as the nav stays mounted.
  useEffect(() => setHasFailed(false), [logoUrl])

  if (!logoUrl || hasFailed) {
    return (
      <Image
        src={DEFAULT_LOGO_SRC}
        alt=""
        width={px}
        height={px}
        className={cn(box, 'shrink-0 rounded-md')}
        priority
        aria-hidden
      />
    )
  }

  return (
    // Org logos are arbitrary remote URLs, so they use a plain <img> — routing
    // them through next/image would require every client domain in
    // next.config's remotePatterns.
    // eslint-disable-next-line @next/next/no-img-element
    <img
      id="image-location-id-data"
      src={logoUrl}
      alt=""
      className={cn(box, 'shrink-0 rounded-md object-contain')}
      aria-hidden
      onError={() => setHasFailed(true)}
    />
  )
}
