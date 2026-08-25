// @vitest-environment jsdom
/**
 * Tests for the shared status vocabulary.
 *
 * statusTone is the single mapping every table and card uses to colour a state,
 * so a regression here silently mis-colours failures as successes across the app.
 */
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { StatusBadge, statusTone } from '@/components/ui/Badge'

describe('statusTone', () => {
  it.each(['completed', 'success', 'succeeded', 'active', 'healthy', 'passed'])(
    'maps terminal success state %s to success',
    status => {
      expect(statusTone(status)).toBe('success')
    },
  )

  it.each(['failed', 'error', 'crashed', 'cancelled', 'revoked', 'expired'])(
    'maps terminal failure state %s to danger',
    status => {
      expect(statusTone(status)).toBe('danger')
    },
  )

  it.each(['pending', 'queued', 'scheduled', 'stale', 'paused'])(
    'maps attention state %s to warning',
    status => {
      expect(statusTone(status)).toBe('warning')
    },
  )

  it('is case-insensitive so Prefect’s COMPLETED matches the API’s completed', () => {
    expect(statusTone('COMPLETED')).toBe(statusTone('completed'))
  })

  it('normalises spaces and hyphens to the underscore form', () => {
    expect(statusTone('in progress')).toBe('info')
    expect(statusTone('in-progress')).toBe('info')
    expect(statusTone('in_progress')).toBe('info')
  })

  it('falls back to neutral for an unknown state', () => {
    expect(statusTone('flibbertigibbet')).toBe('neutral')
  })

  it.each([null, undefined, ''])('falls back to neutral for %s', value => {
    expect(statusTone(value)).toBe('neutral')
  })
})

describe('StatusBadge', () => {
  it('humanises an underscored status for display', () => {
    render(<StatusBadge status="in_progress" />)

    expect(screen.getByText('in progress')).toBeInTheDocument()
  })

  it('renders "unknown" when the status is missing', () => {
    render(<StatusBadge status={null} />)

    expect(screen.getByText('unknown')).toBeInTheDocument()
  })

  it('prefers an explicit label over the raw status', () => {
    render(<StatusBadge status="failed" label="3 of 5 failed" />)

    expect(screen.getByText('3 of 5 failed')).toBeInTheDocument()
  })
})
