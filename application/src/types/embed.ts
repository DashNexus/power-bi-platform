/**
 * The embed technologies a dashboard may use.
 *
 * Must match `EmbedType` in `api/app/schemas/dashboard.py` — the API validates
 * against a Literal, so a value only the frontend knows about is a 422 in the
 * user's face rather than a broken embed.
 *
 * - `powerbi` — an authenticated report, embedded with a short-lived token.
 * - `page` — an ordinary URL in an iframe. No credentials, no token flow, and
 *   no BI connection: this is the "just embed this page" case.
 */
export type EmbedType = 'powerbi' | 'page'

/** Human labels for the embed types, for pickers and detail views. */
export const EMBED_TYPE_LABELS: Record<EmbedType, string> = {
  powerbi: 'Power BI report',
  page: 'Page embed (URL)',
}
