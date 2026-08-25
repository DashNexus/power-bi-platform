'use client'

/**
 * Card/list view preference, persisted per listing page.
 *
 * Stored in localStorage rather than the URL so the choice follows the user
 * between visits. Reads lazily on mount (not during render) because
 * localStorage does not exist while the Server Component HTML is produced —
 * reading it in the initial state would hydrate-mismatch.
 */
import { useCallback, useEffect, useState } from 'react'

export type ViewMode = 'card' | 'list'

const PREFIX = 'portal:view:'

export function useViewMode(
  storageKey: string,
  defaultView: ViewMode = 'card',
): [ViewMode, (next: ViewMode) => void] {
  const [view, setView] = useState<ViewMode>(defaultView)

  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(PREFIX + storageKey)
      if (stored === 'card' || stored === 'list') setView(stored)
    } catch {
      // Private mode or a blocked origin — the default is fine.
    }
  }, [storageKey])

  const update = useCallback(
    (next: ViewMode) => {
      setView(next)
      try {
        window.localStorage.setItem(PREFIX + storageKey, next)
      } catch {
        // Preference is best-effort; the view still switches for this session.
      }
    },
    [storageKey],
  )

  return [view, update]
}
