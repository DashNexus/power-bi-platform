// @vitest-environment jsdom
/**
 * Tests for the brand lockup's mark.
 *
 * An org `logoUrl` is an arbitrary remote URL, so it can 404, expire, or be
 * blocked long after it was saved. When that happens the lockup has to keep
 * showing a mark rather than degrade to a broken-image glyph, and a replacement
 * logo has to get its own chance to load.
 */
import '@testing-library/jest-dom/vitest'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Brand } from '@/components/ui'

/** The mark is `aria-hidden`, so it is unreachable by role. */
function mark(container: HTMLElement): HTMLImageElement {
  const img = container.querySelector('img')
  if (!img) throw new Error('no mark rendered')
  return img
}

describe('Brand', () => {
  it('renders the app icon when the org has no logo', () => {
    const { container } = render(<Brand />)

    expect(mark(container).src).toContain('android-chrome-512x512')
  })

  it('renders the org logo when one is set', () => {
    const { container } = render(<Brand name="Acme" logoUrl="https://cdn.test/acme.png" />)

    expect(mark(container).src).toBe('https://cdn.test/acme.png')
  })

  it('falls back to the app icon when the org logo fails to load', () => {
    const { container } = render(<Brand name="Acme" logoUrl="https://cdn.test/gone.png" />)

    fireEvent.error(mark(container))

    expect(mark(container).src).toContain('android-chrome-512x512')
  })

  it('gives a replacement logo its own chance to load', () => {
    const { container, rerender } = render(<Brand name="Acme" logoUrl="https://cdn.test/gone.png" />)
    fireEvent.error(mark(container))

    rerender(<Brand name="Acme" logoUrl="https://cdn.test/new.png" />)

    expect(mark(container).src).toBe('https://cdn.test/new.png')
  })

  it('keeps the org name as the accessible label when the logo fails', () => {
    const { container } = render(<Brand name="Acme" logoUrl="https://cdn.test/gone.png" />)

    fireEvent.error(mark(container))

    expect(screen.getAllByText('Acme').length).toBeGreaterThan(0)
  })
})
