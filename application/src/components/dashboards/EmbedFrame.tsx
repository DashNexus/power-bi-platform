'use client'

/**
 * Iframe wrapper for embedded dashboards.
 *
 * Use this as the base for all iframe-backed embed types (public Tableau, Looker
 * Studio, arbitrary URLs). Power BI and Tableau Server have their own SDK-backed
 * components.
 */
import { cn } from '@/lib/utils'

interface EmbedFrameProps {
  src: string
  title: string
  className?: string
}

export function EmbedFrame({ src, title, className }: EmbedFrameProps) {
  return (
    <iframe
      src={src}
      title={title}
      // `bg-transparent` keeps the app's surface showing through wherever the
      // embedded document leaves its own background unpainted. No radius of its
      // own — the container clips, so a rounded iframe only shows as a seam of
      // container background in each corner.
      className={cn('h-full w-full border-0 bg-transparent', className)}
      // allow-popups-to-escape-sandbox: Tableau Public's "open in new tab" and
      // Looker Studio's external links target _blank; without it they open into a
      // sandboxed context that immediately fails.
      sandbox="allow-scripts allow-same-origin allow-forms allow-popups allow-popups-to-escape-sandbox allow-downloads"
      allowFullScreen
    />
  )
}
