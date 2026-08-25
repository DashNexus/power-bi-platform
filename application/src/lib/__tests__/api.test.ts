/**
 * Unit tests for lib/api.ts.
 *
 * The global setup mocks @/lib/api for other test files. This file unmocks it
 * first (vi.unmock is hoisted) so it tests the real implementation.
 * @/lib/auth is mocked to avoid network calls and provide a predictable token.
 */
import { describe, it, expect, vi, afterEach } from 'vitest'

// Unmock @/lib/api so this file tests the real implementation, not the stub
// from setup.ts. vi.unmock() is hoisted above the imports that follow.
vi.unmock('@/lib/api')

vi.mock('@/lib/auth', () => ({
  auth: vi.fn().mockResolvedValue({ user: { access_token: 'server-token-abc' } }),
  authConfig: { providers: [], callbacks: {}, pages: {} },
  handlers: {},
  signIn: vi.fn(),
  signOut: vi.fn(),
}))

import { apiFetch, createClientFetch, errorMessageFrom, ApiError } from '@/lib/api'

// ─── helpers ──────────────────────────────────────────────────────────────────

function makeFetch(status: number, body: unknown, ok = status >= 200 && status < 300) {
  return vi.fn().mockResolvedValue({
    ok,
    status,
    statusText: ok ? 'OK' : 'Error',
    json: vi.fn().mockResolvedValue(body),
  })
}

// ─── apiFetch (server-side) ────────────────────────────────────────────────────

describe('apiFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('injects Authorization: Bearer header from the session token', async () => {
    const mockFetch = makeFetch(200, { ok: true })
    vi.stubGlobal('fetch', mockFetch)

    await apiFetch('/users')

    const [url, init] = mockFetch.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }]
    expect(url).toContain('/users')
    expect(init.headers['Authorization']).toBe('Bearer server-token-abc')
  })

  it('appends searchParams to the request URL', async () => {
    const mockFetch = makeFetch(200, [])
    vi.stubGlobal('fetch', mockFetch)

    await apiFetch('/data/orders', { searchParams: { limit: 50, offset: 100 } })

    const [url] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('limit=50')
    expect(url).toContain('offset=100')
  })

  it('returns undefined for 204 No Content', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 204, json: vi.fn() })
    vi.stubGlobal('fetch', mockFetch)

    const result = await apiFetch('/delete-op')
    expect(result).toBeUndefined()
  })

  it('throws ApiError on non-2xx HTTP status', async () => {
    const mockFetch = makeFetch(404, { detail: 'Resource not found' }, false)
    vi.stubGlobal('fetch', mockFetch)

    await expect(apiFetch('/missing')).rejects.toThrow(ApiError)
  })

  it('ApiError carries the HTTP status code', async () => {
    const mockFetch = makeFetch(403, { detail: 'Forbidden' }, false)
    vi.stubGlobal('fetch', mockFetch)

    let caught: unknown
    try {
      await apiFetch('/protected')
    } catch (err) {
      caught = err
    }
    expect(caught).toBeInstanceOf(ApiError)
    expect((caught as ApiError).status).toBe(403)
  })

  it('uses the detail field from the JSON error body as the message', async () => {
    const mockFetch = makeFetch(422, { detail: 'Validation failed' }, false)
    vi.stubGlobal('fetch', mockFetch)

    await expect(apiFetch('/validate')).rejects.toThrow('Validation failed')
  })

  it('falls back to statusText when JSON body has no detail field', async () => {
    const mockFetch = vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      statusText: 'Internal Server Error',
      json: vi.fn().mockRejectedValue(new Error('not json')),
    })
    vi.stubGlobal('fetch', mockFetch)

    await expect(apiFetch('/crash')).rejects.toThrow('Internal Server Error')
  })
})

// ─── createClientFetch (client-side) ──────────────────────────────────────────

describe('createClientFetch', () => {
  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('injects the provided access token as Bearer header', async () => {
    const mockFetch = makeFetch(200, { rows: [] })
    vi.stubGlobal('fetch', mockFetch)

    const clientFetch = createClientFetch('client-tok-xyz')
    await clientFetch('/data/orders')

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }]
    expect(init.headers['Authorization']).toBe('Bearer client-tok-xyz')
  })

  it('makes requests without Authorization header when token is undefined', async () => {
    const mockFetch = makeFetch(200, [])
    vi.stubGlobal('fetch', mockFetch)

    const clientFetch = createClientFetch(undefined)
    await clientFetch('/public')

    const [, init] = mockFetch.mock.calls[0] as [string, RequestInit & { headers: Record<string, string> }]
    expect(init.headers['Authorization']).toBeUndefined()
  })

  it('appends searchParams to the URL', async () => {
    const mockFetch = makeFetch(200, [])
    vi.stubGlobal('fetch', mockFetch)

    const clientFetch = createClientFetch('tok')
    await clientFetch('/data/orders', { searchParams: { limit: 25, page: 2 } })

    const [url] = mockFetch.mock.calls[0] as [string, RequestInit]
    expect(url).toContain('limit=25')
    expect(url).toContain('page=2')
  })

  it('throws ApiError on non-2xx response', async () => {
    const mockFetch = makeFetch(401, { detail: 'Unauthorized' }, false)
    vi.stubGlobal('fetch', mockFetch)

    const clientFetch = createClientFetch('expired')
    await expect(clientFetch('/secure')).rejects.toThrow(ApiError)
  })

  it('returns undefined for 204 No Content', async () => {
    const mockFetch = vi.fn().mockResolvedValue({ ok: true, status: 204, json: vi.fn() })
    vi.stubGlobal('fetch', mockFetch)

    const clientFetch = createClientFetch('tok')
    const result = await clientFetch('/delete')
    expect(result).toBeUndefined()
  })
})

describe('errorMessageFrom', () => {
  it('uses a plain detail string as-is', () => {
    expect(errorMessageFrom({ detail: 'Report not found' }, 'fallback')).toBe('Report not found')
  })

  it('renders a FastAPI validation error instead of [object Object]', () => {
    // 422 sends detail as a list of per-field objects. Passed through unchanged
    // it stringifies to "[object Object]" — the one error that could say what
    // to fix became the least readable of them all.
    const body = {
      detail: [
        { loc: ['body', 'items', 0, 'href'], msg: 'A link must be an internal path' },
        { loc: ['body', 'items', 1, 'label'], msg: 'String should have at least 1 character' },
      ],
    }

    expect(errorMessageFrom(body, 'fallback')).toBe(
      'items → 0 → href: A link must be an internal path; ' +
        'items → 1 → label: String should have at least 1 character',
    )
  })

  it('drops the leading "body" from the field path', () => {
    const body = { detail: [{ loc: ['body', 'name'], msg: 'is required' }] }

    expect(errorMessageFrom(body, 'fallback')).toBe('name: is required')
  })

  it('uses the message alone when there is no field path', () => {
    expect(errorMessageFrom({ detail: [{ msg: 'malformed request' }] }, 'fallback')).toBe(
      'malformed request',
    )
  })

  it('falls back for an empty, missing, or unparseable body', () => {
    expect(errorMessageFrom(null, 'Service Unavailable')).toBe('Service Unavailable')
    expect(errorMessageFrom({}, 'Service Unavailable')).toBe('Service Unavailable')
    expect(errorMessageFrom({ detail: '' }, 'Service Unavailable')).toBe('Service Unavailable')
    expect(errorMessageFrom({ detail: [] }, 'Service Unavailable')).toBe('Service Unavailable')
  })
})
