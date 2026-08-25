/**
 * Turn a pasted "share" URL into one that actually embeds.
 *
 * Tableau Public and Looker Studio both hand out share links from their UI, and
 * neither embeds as-is: Tableau serves its full site page (nav, toolbar, viz
 * home) unless `:embed=y` is present, and `:redirect=auth` makes the framed page
 * attempt a top-level navigation that the iframe sandbox blocks — the symptom is
 * an empty frame. Normalising at render time rather than at save time also fixes
 * dashboards that were saved with a raw share link.
 */

/** Params Tableau adds to a share link that must not survive into an embed. */
const TABLEAU_SHARE_ONLY = [':redirect', ':origin', ':sid']

/** Params this app owns, so a pasted value never fights the ones set below. */
const TABLEAU_MANAGED = [':embed', ':showvizhome', ':toolbar', ':tabs', ':display_count']

/**
 * Split a query string into literal key/value pairs.
 *
 * Deliberately not `URLSearchParams`: Tableau's parameter names start with a
 * colon, and round-tripping through URLSearchParams percent-encodes it to
 * `%3Aembed`. Servers generally decode that, but Tableau's own documentation and
 * every working example use a literal `:`, so this keeps the bytes as-is.
 */
function splitQuery(query: string): Array<[string, string]> {
  if (!query) return []
  return query
    .replace(/^\?/, '')
    .split('&')
    .filter(Boolean)
    .map(pair => {
      const index = pair.indexOf('=')
      return index === -1
        ? ([pair, ''] as [string, string])
        : ([pair.slice(0, index), pair.slice(index + 1)] as [string, string])
    })
}

function joinQuery(pairs: Array<[string, string]>): string {
  if (pairs.length === 0) return ''
  return `?${pairs.map(([key, value]) => (value === '' ? key : `${key}=${value}`)).join('&')}`
}

interface PublicEmbedOptions {
  /**
   * Hex colour (no leading `#`) for the area Tableau draws around the viz. The
   * viz canvas itself takes its colour from the workbook, which an embedder
   * cannot override, so this is what stops a light gutter appearing in dark mode.
   */
  backgroundColor?: string
}

function normalizeTableauPublic(url: URL, options: PublicEmbedOptions): string {
  // Not a viz path (a profile or search page) — nothing sensible to rewrite.
  if (!url.pathname.includes('/views/')) return url.toString()

  const kept = splitQuery(url.search).filter(([key]) => {
    const lower = key.toLowerCase()
    return !TABLEAU_SHARE_ONLY.includes(lower) && !TABLEAU_MANAGED.includes(lower)
  })

  kept.push([':embed', 'y'])
  kept.push([':showVizHome', 'no'])
  // Toolbar and tabs are Tableau's own chrome; the app supplies its own header.
  kept.push([':toolbar', 'no'])
  kept.push([':tabs', 'no'])
  kept.push([':display_count', 'no'])
  if (options.backgroundColor) {
    kept.push([':bgcolor', options.backgroundColor.replace(/^#/, '')])
  }

  return `${url.origin}${url.pathname}${joinQuery(kept)}`
}

function normalizeLookerStudio(url: URL): string {
  // Looker Studio's share link is /reporting/…; only /embed/reporting/… frames.
  if (url.pathname.startsWith('/embed/')) return url.toString()
  if (url.pathname.startsWith('/reporting/')) {
    return `${url.origin}/embed${url.pathname}${url.search}`
  }
  return url.toString()
}

/**
 * Return an embeddable form of `raw`, or `raw` unchanged when it is not a
 * recognised public surface (or not a URL at all — validation is the caller's).
 */
export function normalizePublicEmbedUrl(raw: string, options: PublicEmbedOptions = {}): string {
  const trimmed = raw.trim()
  if (!trimmed) return trimmed

  let url: URL
  try {
    url = new URL(trimmed)
  } catch {
    return trimmed
  }

  const host = url.hostname.toLowerCase()
  if (host === 'public.tableau.com' || host.endsWith('.public.tableau.com')) {
    return normalizeTableauPublic(url, options)
  }
  if (host === 'lookerstudio.google.com' || host === 'datastudio.google.com') {
    return normalizeLookerStudio(url)
  }
  return url.toString()
}

/** True when `raw` needed rewriting to be embeddable. */
export function isShareOnlyUrl(raw: string): boolean {
  return normalizePublicEmbedUrl(raw) !== raw.trim()
}
