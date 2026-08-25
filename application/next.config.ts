import type { NextConfig } from 'next'

const nextConfig: NextConfig = {
  typedRoutes: false,
  // Emit .next/standalone: a self-contained server plus only the node_modules it
  // actually reaches. The container copies that instead of installing
  // dependencies, which is what keeps the runtime image small and free of the
  // build toolchain.
  output: 'standalone',
  // Allows a build to target a scratch directory when the default .next is held
  // open by another process (a running dev server, or a Windows file lock).
  ...(process.env.NEXT_DIST_DIR ? { distDir: process.env.NEXT_DIST_DIR } : {}),
  // Tree-shake per-icon imports instead of pulling the full icon library
  // into every client chunk that imports from 'lucide-react'.
  experimental: {
    optimizePackageImports: ['lucide-react'],
  },
  images: {
    remotePatterns: [
      { protocol: 'https', hostname: '**' },
    ],
  },
}

export default nextConfig
