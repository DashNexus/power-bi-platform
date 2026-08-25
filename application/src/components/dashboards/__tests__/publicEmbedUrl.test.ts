/**
 * Tests for share-link → embed-URL conversion.
 *
 * Tableau Public hands out a link carrying `:redirect=auth` and no `:embed=y`.
 * Framed as-is it attempts a top-level navigation the sandbox blocks, so the
 * dashboard renders as an empty box — the exact symptom that prompted this.
 */
import { describe, expect, it } from 'vitest'
import { isShareOnlyUrl, normalizePublicEmbedUrl } from '../publicEmbedUrl'

// The URL as copied from Tableau Public's share dialog.
const SHARE_LINK =
  'https://public.tableau.com/views/test_20190116Urban_vulnerability_ideasFR_0/mainpage' +
  '?:language=en-US&:sid=&:redirect=auth&:display_count=n&:origin=viz_share_link'

describe('normalizePublicEmbedUrl — Tableau Public', () => {
  it('adds the embed flag, without which Tableau serves its full site page', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).toContain(':embed=y')
  })

  it('drops :redirect=auth, which framed causes a blocked top-level navigation', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).not.toContain(':redirect')
  })

  it('drops the share-origin marker', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).not.toContain(':origin')
  })

  it('drops the empty session id', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).not.toContain(':sid')
  })

  it('hides the Tableau toolbar', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).toContain(':toolbar=no')
  })

  it('hides the sheet tabs', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).toContain(':tabs=no')
  })

  it('suppresses the viz-home chrome', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).toContain(':showVizHome=no')
  })

  it('keeps colons literal rather than percent-encoding them', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).not.toContain('%3A')
  })

  it('preserves the viz path untouched', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).toContain(
      '/views/test_20190116Urban_vulnerability_ideasFR_0/mainpage',
    )
  })

  it('keeps params it does not own, such as :language', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).toContain(':language=en-US')
  })

  it('passes a background colour through when supplied', () => {
    const result = normalizePublicEmbedUrl(SHARE_LINK, { backgroundColor: '0b1220' })

    expect(result).toContain(':bgcolor=0b1220')
  })

  it('strips a leading hash from the background colour', () => {
    const result = normalizePublicEmbedUrl(SHARE_LINK, { backgroundColor: '#0b1220' })

    expect(result).toContain(':bgcolor=0b1220')
  })

  it('omits the background colour when none is resolved', () => {
    expect(normalizePublicEmbedUrl(SHARE_LINK)).not.toContain(':bgcolor')
  })

  it('does not duplicate params when run on its own output', () => {
    const once = normalizePublicEmbedUrl(SHARE_LINK)
    const twice = normalizePublicEmbedUrl(once)

    expect(twice).toBe(once)
  })

  it('overrides a pasted :toolbar=yes rather than appending a second copy', () => {
    const result = normalizePublicEmbedUrl(
      'https://public.tableau.com/views/Book/Sheet?:toolbar=yes',
    )

    expect(result).toContain(':toolbar=no')
    expect(result).not.toContain(':toolbar=yes')
  })

  it('leaves a non-viz Tableau Public page alone', () => {
    const profile = 'https://public.tableau.com/app/profile/someone'

    expect(normalizePublicEmbedUrl(profile)).toBe(profile)
  })
})

describe('normalizePublicEmbedUrl — Looker Studio', () => {
  it('rewrites a share link to the embed path', () => {
    const result = normalizePublicEmbedUrl(
      'https://lookerstudio.google.com/reporting/abc-123/page/p_1',
    )

    expect(result).toBe('https://lookerstudio.google.com/embed/reporting/abc-123/page/p_1')
  })

  it('leaves an already-embeddable URL unchanged', () => {
    const embed = 'https://lookerstudio.google.com/embed/reporting/abc-123/page/p_1'

    expect(normalizePublicEmbedUrl(embed)).toBe(embed)
  })

  it('handles the legacy datastudio host', () => {
    const result = normalizePublicEmbedUrl(
      'https://datastudio.google.com/reporting/abc-123/page/p_1',
    )

    expect(result).toContain('/embed/reporting/')
  })
})

describe('normalizePublicEmbedUrl — other input', () => {
  it('passes an unrecognised host through', () => {
    const other = 'https://example.com/embed/thing'

    expect(normalizePublicEmbedUrl(other)).toBe(other)
  })

  it('returns a non-URL unchanged rather than throwing', () => {
    expect(normalizePublicEmbedUrl('not a url')).toBe('not a url')
  })

  it('returns empty input unchanged', () => {
    expect(normalizePublicEmbedUrl('')).toBe('')
  })

  it('trims surrounding whitespace', () => {
    expect(normalizePublicEmbedUrl('  https://example.com/x  ')).toBe('https://example.com/x')
  })
})

describe('isShareOnlyUrl', () => {
  it('flags a Tableau share link as needing conversion', () => {
    expect(isShareOnlyUrl(SHARE_LINK)).toBe(true)
  })

  it('does not flag an already-embeddable URL', () => {
    expect(isShareOnlyUrl(normalizePublicEmbedUrl(SHARE_LINK))).toBe(false)
  })

  it('does not flag an unrelated URL', () => {
    expect(isShareOnlyUrl('https://example.com/embed/thing')).toBe(false)
  })
})
