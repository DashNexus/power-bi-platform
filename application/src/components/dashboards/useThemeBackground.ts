'use client'

/**
 * Resolve the page background token to a concrete hex value.
 *
 * Embedded BI surfaces are cross-origin, so their document background cannot be
 * made transparent from here — the best available substitute is telling the
 * provider which colour to paint, which needs a literal hex rather than a CSS
 * variable. Re-reads when the theme class flips so a dark-mode toggle does not
 * leave a light gutter around the viz.
 */
import { useEffect, useState } from 'react'

export function useThemeBackground(): string | undefined {
  const [color, setColor] = useState<string | undefined>(undefined)

  useEffect(() => {
    const root = document.documentElement

    const read = () => {
      const value = getComputedStyle(root).getPropertyValue('--background').trim()
      // Providers take `RRGGBB`; anything else (oklch, a named colour) is unusable,
      // so leave it unset rather than sending something the provider will reject.
      const hex = value.match(/^#([0-9a-f]{6})$/i)
      setColor(hex ? hex[1] : undefined)
    }

    read()
    const observer = new MutationObserver(read)
    observer.observe(root, { attributes: true, attributeFilter: ['class', 'style'] })
    return () => observer.disconnect()
  }, [])

  return color
}
