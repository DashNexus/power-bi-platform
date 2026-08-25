/**
 * Vitest global setup.
 *
 * Mocks modules that are unavailable outside the Next.js runtime so that
 * server-side lib/* files can be imported and tested in a plain Node environment.
 */
import type * as ReactModule from 'react'
import { vi } from 'vitest'

// React's cache() requires the React server runtime. Replace it with a
// simple passthrough function so cached helpers run normally in tests.
vi.mock('react', async (importOriginal) => {
  const actual = await importOriginal<typeof ReactModule>()
  return {
    ...actual,
    cache: (fn: (...args: unknown[]) => unknown) => fn,
  }
})

// apiFetch calls Next.js headers/cookies; stub it out for unit tests.
vi.mock('@/lib/api', () => ({
  apiFetch: vi.fn(),
  createClientFetch: vi.fn(),
}))
