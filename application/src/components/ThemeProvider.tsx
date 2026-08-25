'use client'

/**
 * next-themes provider wrapper.
 *
 * Must be a client component because it uses React context. Wrap in the root
 * layout so the theme is available everywhere.
 */
import { ThemeProvider as NextThemesProvider } from 'next-themes'
import type { ThemeProviderProps } from 'next-themes'

export function ThemeProvider({ children, ...props }: ThemeProviderProps) {
  return <NextThemesProvider {...props}>{children}</NextThemesProvider>
}
