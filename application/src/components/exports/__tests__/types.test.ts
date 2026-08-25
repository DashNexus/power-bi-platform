// @vitest-environment jsdom
/**
 * Tests for the exports helpers.
 *
 * These are the bits of the run log that are computed rather than displayed
 * verbatim, so they are the bits that can be quietly wrong.
 */
import { describe, expect, it } from 'vitest'
import {
  EMPTY_RUN_FILTERS,
  daysUntilExpiry,
  formatBytes,
  hasRunFilters,
  runFilterParams,
} from '@/components/exports/types'

describe('formatBytes', () => {
  it('renders a missing size as a dash rather than 0 B', () => {
    expect(formatBytes(null)).toBe('—')
  })

  it('leaves byte counts unscaled', () => {
    expect(formatBytes(0)).toBe('0 B')
    expect(formatBytes(999)).toBe('999 B')
  })

  it('scales to KB, MB and GB', () => {
    expect(formatBytes(2048)).toBe('2.0 KB')
    expect(formatBytes(5 * 1024 * 1024)).toBe('5.0 MB')
    expect(formatBytes(3 * 1024 * 1024 * 1024)).toBe('3.0 GB')
  })

  it('drops the decimal once the number is wide enough not to need it', () => {
    expect(formatBytes(15 * 1024)).toBe('15 KB')
  })
})

describe('daysUntilExpiry', () => {
  it('returns null when nothing expires', () => {
    expect(daysUntilExpiry(null)).toBeNull()
  })

  it('rounds up, so a result expiring in a few hours still reads as a day left', () => {
    const soon = new Date(Date.now() + 3 * 3600_000).toISOString()

    expect(daysUntilExpiry(soon)).toBe(1)
  })

  it('counts the full retention window', () => {
    const later = new Date(Date.now() + 30 * 86_400_000).toISOString()

    expect(daysUntilExpiry(later)).toBe(30)
  })

  it('clamps an already-expired result to zero rather than going negative', () => {
    const past = new Date(Date.now() - 86_400_000).toISOString()

    expect(daysUntilExpiry(past)).toBe(0)
  })
})

describe('hasRunFilters', () => {
  it('treats no filters as no filters', () => {
    expect(hasRunFilters(EMPTY_RUN_FILTERS)).toBe(false)
  })

  it('ignores a search box holding only whitespace', () => {
    expect(hasRunFilters({ ...EMPTY_RUN_FILTERS, search: '   ' })).toBe(false)
  })

  it('reports each filter on its own', () => {
    expect(hasRunFilters({ ...EMPTY_RUN_FILTERS, search: 'orders' })).toBe(true)
    expect(hasRunFilters({ ...EMPTY_RUN_FILTERS, status: 'failed' })).toBe(true)
    expect(hasRunFilters({ ...EMPTY_RUN_FILTERS, triggerType: 'manual' })).toBe(true)
  })
})

describe('runFilterParams', () => {
  it('always carries the limit', () => {
    expect(runFilterParams(EMPTY_RUN_FILTERS, 25)).toBe('limit=25')
  })

  it('omits empty filters rather than sending them blank', () => {
    // `status=` reaches the API as an empty string, and the run-log endpoints
    // reject a status no run can have — so a blank filter would 400.
    expect(runFilterParams(EMPTY_RUN_FILTERS, 100)).not.toContain('status')
    expect(runFilterParams(EMPTY_RUN_FILTERS, 100)).not.toContain('search')
  })

  it('trims the search term', () => {
    expect(runFilterParams({ ...EMPTY_RUN_FILTERS, search: '  orders  ' }, 25)).toBe(
      'limit=25&search=orders',
    )
  })

  it('drops a search of only whitespace', () => {
    expect(runFilterParams({ ...EMPTY_RUN_FILTERS, search: '   ' }, 25)).toBe('limit=25')
  })

  it('sends the trigger as trigger_type, matching the column', () => {
    expect(runFilterParams({ ...EMPTY_RUN_FILTERS, triggerType: 'schedule' }, 25)).toBe(
      'limit=25&trigger_type=schedule',
    )
  })

  it('escapes a term that would otherwise break the query string', () => {
    expect(runFilterParams({ ...EMPTY_RUN_FILTERS, search: '100% & up' }, 25)).toBe(
      'limit=25&search=100%25+%26+up',
    )
  })

  it('combines every filter', () => {
    expect(
      runFilterParams({ search: 'orders', status: 'failed', triggerType: 'manual' }, 50),
    ).toBe('limit=50&search=orders&status=failed&trigger_type=manual')
  })
})
