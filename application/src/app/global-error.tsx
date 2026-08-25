'use client'

/**
 * Last-resort boundary for errors thrown by the root layout itself.
 *
 * Must render its own <html>/<body>, because a failure here means the root
 * layout never mounted. Styling is inline for the same reason — the stylesheet
 * is imported by the layout that just failed.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: '100vh',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          background: '#0b1220',
          color: '#f8fafc',
          fontFamily: 'system-ui, -apple-system, Segoe UI, sans-serif',
          padding: '1.5rem',
        }}
      >
        <div style={{ maxWidth: '32rem', textAlign: 'center' }}>
          <h1 style={{ fontSize: '1.25rem', fontWeight: 600, margin: '0 0 0.5rem' }}>
            Sec Dash could not start
          </h1>
          <p style={{ color: '#94a3b8', fontSize: '0.875rem', margin: '0 0 1.25rem' }}>
            The application failed to load. Reload the page — if it keeps happening, contact your
            administrator{error.digest ? ` and quote reference ${error.digest}` : ''}.
          </p>
          <button
            type="button"
            onClick={reset}
            style={{
              background: '#2d8cff',
              color: '#071019',
              border: 0,
              borderRadius: '0.5rem',
              padding: '0.5rem 1rem',
              fontSize: '0.875rem',
              fontWeight: 600,
              cursor: 'pointer',
            }}
          >
            Reload
          </button>
        </div>
      </body>
    </html>
  )
}
