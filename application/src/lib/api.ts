/**
 * Typed fetch client for the FastAPI backend.
 *
 * Injects the current session's access_token as a Bearer header on every
 * request. Use apiFetch() exclusively — never call fetch() directly.
 *
 * apiFetch is server-only — it dynamically imports auth() at call time so
 * that this module can be bundled into client components (for createClientFetch)
 * without pulling auth.ts (and its top-level getEnabledProviders() call) into
 * the browser bundle.
 */

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message)
    this.name = 'ApiError'
  }
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

/** One entry of FastAPI's 422 body: which field failed, and why. */
interface ValidationDetail {
  loc?: Array<string | number>
  msg?: string
}

/**
 * Turn an error response body into a message worth showing someone.
 *
 * FastAPI sends `detail` as a string for a raised HTTPException, but as a list
 * of per-field objects when Pydantic rejects the request body. Passing the list
 * through unchanged renders as "[object Object]", so a validation error — the
 * one kind that could actually tell the user what to fix — was the least
 * useful of them all.
 */
export function errorMessageFrom(body: unknown, fallback: string): string {
  const detail = (body as { detail?: unknown } | null)?.detail
  if (typeof detail === 'string' && detail) return detail
  if (Array.isArray(detail) && detail.length > 0) {
    const messages = (detail as ValidationDetail[])
      .map(entry => {
        // loc is ["body", "items", 0, "href"] — the leading "body" is noise.
        const field = (entry.loc ?? []).slice(1).join(' → ')
        const msg = entry.msg ?? 'is invalid'
        return field ? `${field}: ${msg}` : msg
      })
      .filter(Boolean)
    if (messages.length > 0) return messages.join('; ')
  }
  return fallback
}


/**
 * Fetch from the FastAPI backend (server-side — uses auth() to get token).
 *
 * @param path - API path relative to NEXT_PUBLIC_API_URL (e.g. "/data/orders").
 * @param options - Standard RequestInit plus optional searchParams map.
 * @returns Parsed JSON response typed as T.
 * @throws {ApiError} On non-2xx HTTP status codes.
 */
export async function apiFetch<T = unknown>(
  path: string,
  options?: RequestInit & { searchParams?: Record<string, string | number | boolean> },
): Promise<T> {
  const { auth } = await import('@/lib/auth')
  const session = await auth()
  const url = new URL(`${API_BASE}${path}`)

  if (options?.searchParams) {
    Object.entries(options.searchParams).forEach(([k, v]) =>
      url.searchParams.set(k, String(v)),
    )
  }

  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...(options?.headers as Record<string, string>),
  }

  if (session?.user?.access_token) {
    headers['Authorization'] = `Bearer ${session.user.access_token}`
  }

  const { searchParams: _unused, ...restOptions } = options ?? {}
  const res = await fetch(url.toString(), { ...restOptions, headers })

  if (!res.ok) {
    const body = await res.json().catch(() => null)
    throw new ApiError(res.status, errorMessageFrom(body, res.statusText))
  }

  if (res.status === 204) return undefined as T
  return res.json() as Promise<T>
}

/**
 * Create a client-side fetch function bound to the given access token.
 *
 * Use this in client components where auth() is not available (client-side).
 * Obtain the access_token from useSession().
 *
 * @param accessToken - Bearer token from the current session.
 */
export function createClientFetch(accessToken: string | undefined) {
  return async function clientFetch<T = unknown>(
    path: string,
    options?: RequestInit & { searchParams?: Record<string, string | number | boolean> },
  ): Promise<T> {
    const urlObj = new URL(`${API_BASE}${path}`)
    if (options?.searchParams) {
      Object.entries(options.searchParams).forEach(([k, v]) =>
        urlObj.searchParams.set(k, String(v)),
      )
    }
    const url = urlObj.toString()

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
      ...(options?.headers as Record<string, string>),
    }

    if (accessToken) headers['Authorization'] = `Bearer ${accessToken}`

    const { searchParams: _unused, ...restOptions } = options ?? {}
    const res = await fetch(url, { ...restOptions, headers })

    if (!res.ok) {
      // Notify the SessionExpiryWatcher so it can sign the user out cleanly
      if (res.status === 401 && typeof window !== 'undefined') {
        window.dispatchEvent(new Event('auth:expired'))
      }
      const body = await res.json().catch(() => null)
      throw new ApiError(res.status, errorMessageFrom(body, res.statusText))
    }

    if (res.status === 204) return undefined as T
    return res.json() as Promise<T>
  }
}
