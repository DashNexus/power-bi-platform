'use client'

/**
 * Root authenticated application shell.
 *
 * All users see the PortalNav at the top. Admin users additionally see the
 * collapsible sidebar on the left for management functions.
 */
import { useState, useEffect } from 'react'
import type { Session } from 'next-auth'
import type { PortalSettings } from '@/lib/portal'
import type { ResourceAccess } from '@/lib/navAccess'
import { Sidebar } from '@/components/layout/Sidebar'
import { PortalNav } from '@/components/layout/PortalNav'
import { CommandPalette } from '@/components/ui/CommandPalette'
import { hasRole } from '@/lib/permissions'

interface AppShellProps {
  session: Session
  orgSettings: PortalSettings | null
  features: Record<string, boolean>
  /** Resources the user may open, for filtering deep links in a custom nav. */
  resourceAccess?: ResourceAccess | null
  children: React.ReactNode
}

export function AppShell({
  session,
  orgSettings,
  features,
  resourceAccess = null,
  children,
}: AppShellProps) {
  const [paletteOpen, setPaletteOpen] = useState(false)
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false)
  const isAdmin = hasRole(session.user.role, 'admin')

  // Persist collapse state across page loads
  useEffect(() => {
    const stored = localStorage.getItem('sidebar-collapsed')
    if (stored === 'true') setSidebarCollapsed(true)
  }, [])

  function toggleSidebar() {
    setSidebarCollapsed(prev => {
      const next = !prev
      localStorage.setItem('sidebar-collapsed', String(next))
      return next
    })
  }

  // Global ⌘K / Ctrl+K opens search from anywhere in the shell.
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
        e.preventDefault()
        setPaletteOpen(open => !open)
      }
    }
    window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [])

  // Non-admin: horizontal nav only, full-width content
  if (!isAdmin) {
    return (
      <div className="h-screen flex flex-col bg-background">
        <PortalNav
          session={session}
          orgSettings={orgSettings}
          features={features}
          navConfig={orgSettings?.nav_config}
          resourceAccess={resourceAccess}
          onSearchOpen={() => setPaletteOpen(true)}
        />
        {/* pt-14 offsets the fixed PortalNav. It lives on this wrapper rather
            than on main so full-bleed pages that zero main's padding still
            clear the nav. */}
        <div className="flex flex-1 min-h-0 min-w-0 flex-col pt-14">
          {/* scrollbar-gutter:stable reserves the vertical scrollbar's width even
              when it is absent. Without it, content growing tall enough to scroll
              narrows the viewport, and a fixed-size embed that had just fit is
              suddenly ~10px too wide — producing a horizontal scrollbar. */}
          <main className="flex flex-1 min-h-0 min-w-0 flex-col overflow-auto [scrollbar-gutter:stable]">
            <div id="page-content" className="flex-1 min-h-0 flex flex-col mx-auto w-full max-w-7xl px-4 py-6 sm:px-6 lg:px-8">
              {children}
            </div>
          </main>
        </div>
        <CommandPalette
          open={paletteOpen}
          onClose={() => setPaletteOpen(false)}
          accessToken={session.user.access_token ?? ''}
        />
      </div>
    )
  }

  // Admin: PortalNav spans full width at top; Sidebar is fixed below it on the left
  const sidebarW = sidebarCollapsed ? 'md:w-16' : 'md:w-64'
  const mainPl = sidebarCollapsed ? 'md:pl-16' : 'md:pl-64'

  return (
    <div className="flex h-screen overflow-hidden bg-background">
      {/* PortalNav — fixed full-width at top, visible to admin users too */}
      <PortalNav
        session={session}
        orgSettings={orgSettings}
        features={features}
        navConfig={orgSettings?.nav_config}
        resourceAccess={resourceAccess}
        onSearchOpen={() => setPaletteOpen(true)}
        showAdminBadge
      />

      {/* Sidebar — starts below the nav bar (top-14) */}
      <aside
        className={`hidden md:flex md:flex-col md:fixed md:top-14 md:bottom-0 md:left-0 border-r border-border bg-card transition-[width] duration-200 overflow-hidden ${sidebarW}`}
      >
        <Sidebar
          role={session.user.role}
          features={features}
          collapsed={sidebarCollapsed}
          onToggleCollapse={toggleSidebar}
        />
      </aside>

      {/* Main area — offset right by the sidebar, down by the nav bar */}
      <div className={`flex flex-1 min-w-0 flex-col pt-14 ${mainPl} transition-[padding] duration-200`}>
        {/* See the note on the non-admin <main>: the reserved gutter is what keeps
            a vertical scrollbar from provoking a horizontal one. */}
        <main className="flex flex-1 min-h-0 min-w-0 flex-col overflow-auto p-6 [scrollbar-gutter:stable]">
          {children}
        </main>
      </div>

      {/* Global command palette */}
      <CommandPalette
        open={paletteOpen}
        onClose={() => setPaletteOpen(false)}
        accessToken={session.user.access_token ?? ''}
      />
    </div>
  )
}
