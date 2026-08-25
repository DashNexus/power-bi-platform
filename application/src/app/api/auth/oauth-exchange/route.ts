/**
 * OAuth token exchange proxy for Auth.js.
 *
 * Auth.js calls this route after a successful OAuth provider sign-in.
 * Forwards the provider token to the FastAPI backend, which provisions the
 * user account on first login and returns a platform JWT pair.
 */
import type { NextRequest} from 'next/server';
import { NextResponse } from 'next/server'

export async function POST(request: NextRequest): Promise<NextResponse> {
  const { provider, access_token, id_token } = (await request.json()) as {
    provider: string
    access_token: string
    id_token?: string
  }

  const res = await fetch(
    `${process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'}/auth/oauth-exchange`,
    {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ provider, access_token, id_token }),
    },
  )

  if (!res.ok) {
    const body = (await res.json().catch(() => ({}))) as { detail?: string }
    return NextResponse.json(
      { error: body.detail ?? 'OAuth exchange failed' },
      { status: 400 },
    )
  }

  return NextResponse.json(await res.json())
}
