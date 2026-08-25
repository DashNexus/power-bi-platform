import type { Metadata, Viewport } from 'next'
import { SessionProvider } from 'next-auth/react'
import { Toaster } from 'sonner'
import { ThemeProvider } from '@/components/ThemeProvider'
import { APP_NAME } from '@/components/ui/Brand'
import './globals.css'

export const metadata: Metadata = {
  // `template` appends the product name to every child route's title, so pages
  // set only their own name (`title: 'Sign in'` → "Sign in — Sec Dash").
  title: {
    default: APP_NAME,
    template: `%s — ${APP_NAME}`,
  },
  description: 'Self-service dashboards, AI chat, and data governance for client analytics.',
  applicationName: APP_NAME,
  // Previously these lived only in public/head-snippet.html, which Next never
  // loads — the icons in public/ were unreachable.
  icons: {
    icon: [
      { url: '/favicon.ico', sizes: 'any' },
      { url: '/favicon-16x16.png', type: 'image/png', sizes: '16x16' },
      { url: '/favicon-32x32.png', type: 'image/png', sizes: '32x32' },
      { url: '/favicon-48x48.png', type: 'image/png', sizes: '48x48' },
    ],
    apple: [{ url: '/apple-touch-icon.png', sizes: '180x180' }],
  },
  manifest: '/site.webmanifest',
  appleWebApp: { capable: true, title: APP_NAME, statusBarStyle: 'black-translucent' },
}

export const viewport: Viewport = {
  // Matches --background in each theme so the mobile browser chrome does not
  // flash white on a dark page.
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#f6f8fb' },
    { media: '(prefers-color-scheme: dark)', color: '#0b1220' },
  ],
}

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body suppressHydrationWarning>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {/* refetchInterval: re-check session every 4 min (under the 5-min cache TTL).
              refetchOnWindowFocus: immediately check when the user returns to the tab. */}
          <SessionProvider refetchInterval={4 * 60} refetchOnWindowFocus>
            {children}
          </SessionProvider>
          <Toaster richColors position="top-right" />
        </ThemeProvider>
      </body>
    </html>
  )
}
