'use client'

/**
 * Horizontal navigation bar for standard (non-admin) users.
 *
 * Replaces the sidebar with a simpler top-bar layout. Shows feature-gated
 * navigation links and a user avatar menu identical to the TopBar. When an
 * admin has authored a navigation on /admin/nav-config, those items render
 * instead of the defaults, including dropdown menus for grouped links.
 *
 * Every configured link is filtered through `isHrefAccessible`, so the nav can
 * name a dashboard the viewer cannot open without showing it to them. That is a
 * display rule only — the route itself still enforces access.
 *
 * The nav link area scrolls horizontally when items overflow, with
 * left/right arrow buttons that fade in at each edge. No scrollbar is shown.
 */
import { useState, useEffect, useRef, useCallback } from 'react'
import Link from 'next/link'
import { signOut } from 'next-auth/react'
import type { Session } from 'next-auth'
import {
  Workflow,
  LayoutDashboard,
  LayoutGrid,
  Download,
  FileText,
  Settings,
  Home,
  LogOut,
  Sun,
  Moon,
  Monitor,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Search,
  NotebookText,
} from 'lucide-react'
import { useTheme } from 'next-themes'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { cn } from '@/lib/utils'
import { Avatar } from '@/components/ui'
import type { NavConfigItem, PortalSettings } from '@/lib/portal'
import { isHrefAccessible, type ResourceAccess } from '@/lib/navAccess'
import { Brand } from '@/components/ui/Brand'

interface PortalNavProps {
  session: Session
  orgSettings: PortalSettings | null
  features: Record<string, boolean>
  /** Admin-authored navigation. Empty or absent falls back to the defaults. */
  navConfig?: NavConfigItem[] | null
  /** Resources the user may open, for filtering deep links. */
  resourceAccess?: ResourceAccess | null
  onSearchOpen?: () => void
  showAdminBadge?: boolean
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()
  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          suppressHydrationWarning
          aria-label="Toggle theme"
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        >
          <Sun className="h-4 w-4 dark:hidden" />
          <Moon className="h-4 w-4 hidden dark:block" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content align="end" sideOffset={8} className="z-50 min-w-[140px] rounded-xl border border-border bg-card p-1.5 shadow-lg">
          {[
            { value: 'light', label: 'Light', icon: Sun },
            { value: 'dark', label: 'Dark', icon: Moon },
            { value: 'system', label: 'System', icon: Monitor },
          ].map(({ value, label, icon: Icon }) => (
            <DropdownMenu.Item
              key={value}
              onClick={() => setTheme(value)}
              className={cn(
                'flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm outline-none',
                theme === value
                  ? 'bg-primary-subtle text-info-strong '
                  : 'text-foreground hover:bg-accent ',
              )}
            >
              <Icon className="h-4 w-4" />
              {label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

// ─── ScrollableNav ────────────────────────────────────────────────────────────

function ScrollableNav({ children }: { children: React.ReactNode }) {
  const navRef = useRef<HTMLElement>(null)
  const [canScrollLeft, setCanScrollLeft] = useState(false)
  const [canScrollRight, setCanScrollRight] = useState(false)

  const checkScroll = useCallback(() => {
    const el = navRef.current
    if (!el) return
    setCanScrollLeft(el.scrollLeft > 2)
    setCanScrollRight(el.scrollLeft + el.clientWidth < el.scrollWidth - 2)
  }, [])

  useEffect(() => {
    const el = navRef.current
    if (!el) return
    checkScroll()
    el.addEventListener('scroll', checkScroll, { passive: true })
    const ro = new ResizeObserver(checkScroll)
    ro.observe(el)
    return () => {
      el.removeEventListener('scroll', checkScroll)
      ro.disconnect()
    }
  }, [checkScroll])

  function scrollBy(amount: number) {
    navRef.current?.scrollBy({ left: amount, behavior: 'smooth' })
  }

  return (
    <div className="relative hidden md:block flex-1 min-w-0">
      {/* Left fade + arrow */}
      <div
        className={cn(
          'absolute left-0 inset-y-0 z-10 flex items-center transition-opacity duration-150',
          canScrollLeft ? 'opacity-100' : 'opacity-0 pointer-events-none',
        )}
      >
        <div className="absolute inset-y-0 left-0 w-10 bg-gradient-to-r from-card to-transparent pointer-events-none" />
        <button
          type="button"
          onClick={() => scrollBy(-200)}
          aria-label="Scroll navigation left"
          className="relative flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card shadow-sm hover:bg-accent transition-colors"
        >
          <ChevronLeft className="h-3.5 w-3.5 text-muted-foreground " />
        </button>
      </div>

      {/* Scrollable nav — the <nav> itself is the scroll container */}
      <nav
        ref={navRef}
        className="flex items-center gap-1 overflow-x-auto [&::-webkit-scrollbar]:hidden"
        style={{ scrollbarWidth: 'none' }}
      >
        {children}
      </nav>

      {/* Right fade + arrow */}
      <div
        className={cn(
          'absolute right-0 inset-y-0 z-10 flex items-center justify-end transition-opacity duration-150',
          canScrollRight ? 'opacity-100' : 'opacity-0 pointer-events-none',
        )}
      >
        <div className="absolute inset-y-0 right-0 w-10 bg-gradient-to-l from-card to-transparent pointer-events-none" />
        <button
          type="button"
          onClick={() => scrollBy(200)}
          aria-label="Scroll navigation right"
          className="relative flex h-6 w-6 items-center justify-center rounded-full border border-border bg-card shadow-sm hover:bg-accent transition-colors"
        >
          <ChevronRight className="h-3.5 w-3.5 text-muted-foreground " />
        </button>
      </div>
    </div>
  )
}

// ─── Default nav links ─────────────────────────────────────────────────────────

const DEFAULT_NAV_LINKS = [
  { label: 'Home', href: '/home', icon: Home },
]

// ─── PortalNav ────────────────────────────────────────────────────────────────

export function PortalNav({
  session,
  orgSettings,
  features,
  navConfig,
  resourceAccess = null,
  onSearchOpen,
  showAdminBadge,
}: PortalNavProps) {
  const role = session.user.role

  // Radix's DropdownMenu generates ids with useId(), which can differ between
  // the server pass and the first client pass when the tree is shaped
  // conditionally. Rendering the defaults on both guarantees they match; the
  // configured nav takes over once mounted.
  const [mounted, setMounted] = useState(false)
  useEffect(() => setMounted(true), [])

  const defaultLinks = [
    ...DEFAULT_NAV_LINKS,
    ...(features['dashboards'] ? [{ label: 'Dashboards', href: '/dashboard', icon: LayoutDashboard }] : []),
    ...(features['custom_pages'] ? [{ label: 'Pages', href: '/pages', icon: FileText }] : []),
    ...(features['governance'] ? [{ label: 'Data Dictionary', href: '/data-dicts', icon: NotebookText }] : []),
    ...(features['exports'] ? [{ label: 'Exports', href: '/exports', icon: Download }] : []),
  ]

  return (
    <header className="fixed inset-x-0 top-0 z-30 flex h-14 items-center gap-3 border-b border-border bg-card px-4 ">
      {/* Brand */}
      <Link href="/home" className="shrink-0 rounded-lg">
        <Brand name={orgSettings?.app_name} logoUrl={orgSettings?.logo_url} size="sm" />
      </Link>

      {/* Nav links — scrollable, configured or default */}
      <ScrollableNav>
        {mounted && navConfig && navConfig.length > 0
          ? navConfig.map((item, i) => {
              if (item.type === 'dropdown') {
                const visibleChildren = (item.items ?? []).filter(child =>
                  isHrefAccessible(child.href, features, role, resourceAccess),
                )
                // A menu whose every entry is hidden would open onto nothing.
                if (visibleChildren.length === 0) return null
                return (
                  <DropdownMenu.Root key={`${item.label}-${i}`}>
                    <DropdownMenu.Trigger asChild>
                      <button
                        type="button"
                        className="flex shrink-0 items-center gap-1.5 rounded-lg px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                      >
                        {item.label}
                        <ChevronDown className="h-3.5 w-3.5" />
                      </button>
                    </DropdownMenu.Trigger>
                    <DropdownMenu.Portal>
                      <DropdownMenu.Content
                        align="start"
                        sideOffset={8}
                        className="z-50 min-w-[180px] rounded-xl border border-border bg-card p-1.5 shadow-lg"
                      >
                        {visibleChildren.map((child, ci) => (
                          <DropdownMenu.Item key={`${child.href}-${ci}`} asChild>
                            <Link
                              href={child.href}
                              className="flex cursor-pointer items-center rounded-lg px-3 py-2 text-sm text-foreground outline-none hover:bg-accent"
                            >
                              {child.label}
                            </Link>
                          </DropdownMenu.Item>
                        ))}
                      </DropdownMenu.Content>
                    </DropdownMenu.Portal>
                  </DropdownMenu.Root>
                )
              }
              if (!item.href) return null
              if (!isHrefAccessible(item.href, features, role, resourceAccess)) return null
              return (
                <Link
                  key={`${item.href}-${i}`}
                  href={item.href}
                  className="shrink-0 rounded-lg px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
                >
                  {item.label}
                </Link>
              )
            })
          : defaultLinks.map(({ label, href, icon: Icon }) => (
              <Link
                key={href}
                href={href}
                className="flex shrink-0 items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium text-muted-foreground transition-colors hover:bg-accent hover:text-foreground "
              >
                <Icon className="h-4 w-4" />
                {label}
              </Link>
            ))}
      </ScrollableNav>

      {/* Right side */}
      <div className="ml-auto shrink-0 flex items-center gap-2">
        {onSearchOpen && (
          <button
            type="button"
            aria-label="Open search"
            onClick={onSearchOpen}
            className="flex items-center gap-2 rounded-lg border border-border bg-muted px-3 py-1.5 text-sm text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
          >
            <Search className="h-3.5 w-3.5" />
            <span className="hidden sm:inline">Search</span>
            <kbd className="hidden sm:inline-block ml-1 rounded bg-secondary px-1.5 py-0.5 text-xs text-muted-foreground ">
              ⌘K
            </kbd>
          </button>
        )}
        {showAdminBadge && (
          <Link
            href="/admin"
            className="hidden sm:inline-flex items-center rounded-full bg-primary-subtle px-2.5 py-0.5 text-xs font-medium text-info-strong hover:bg-primary-subtle transition-colors"
          >
            Admin
          </Link>
        )}
        <ThemeToggle />

        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button type="button" suppressHydrationWarning className="flex items-center gap-2 rounded-full focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-1">
              <Avatar
                name={session.user.name}
                email={session.user.email}
                avatarUrl={session.user.avatar_url}
              />
            </button>
          </DropdownMenu.Trigger>
          <DropdownMenu.Portal>
            <DropdownMenu.Content align="end" sideOffset={8} className="z-50 min-w-[220px] rounded-xl border border-border bg-card p-1.5 shadow-lg">
              <div className="px-3 py-2 border-b border-border mb-1">
                <p className="text-sm font-medium text-foreground truncate">
                  {session.user.name ?? 'User'}
                </p>
                <p className="text-xs text-muted-foreground truncate">{session.user.email}</p>
              </div>

              {/* Quick navigation links */}
              <div className="py-1">
                <p className="px-3 py-1 text-xs font-semibold uppercase tracking-wider text-muted-foreground ">
                  Navigate
                </p>
                {[
                  { label: 'Home', href: '/home', icon: Home },
                  { label: 'All Resources', href: '/resources', icon: LayoutGrid },
                  ...(features['dashboards'] ? [{ label: 'Dashboards', href: '/dashboard', icon: LayoutDashboard }] : []),
                  ...(features['custom_pages'] ? [{ label: 'Pages', href: '/pages', icon: FileText }] : []),
                  ...(features['governance'] ? [{ label: 'Data Dictionary', href: '/data-dicts', icon: NotebookText }] : []),
                  ...(features['pipelines'] ? [{ label: 'Data Pipelines', href: '/pipelines', icon: Workflow }] : []),
                  ...(features['exports'] ? [{ label: 'Data Exports', href: '/exports', icon: Download }] : []),
                ].map(({ label, href, icon: Icon }) => (
                  <DropdownMenu.Item key={href} asChild>
                    <Link
                      href={href}
                      className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-1.5 text-sm text-foreground outline-none hover:bg-accent "
                    >
                      <Icon className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                      {label}
                    </Link>
                  </DropdownMenu.Item>
                ))}
              </div>

              <DropdownMenu.Separator className="my-1 h-px bg-muted" />
              <DropdownMenu.Item asChild>
                <Link
                  href="/settings"
                  className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground outline-none hover:bg-accent "
                >
                  <Settings className="h-4 w-4 text-muted-foreground " />
                  Settings
                </Link>
              </DropdownMenu.Item>
              <DropdownMenu.Separator className="my-1 h-px bg-muted" />
              <DropdownMenu.Item
                onClick={() => signOut({ callbackUrl: '/login' })}
                className="flex cursor-pointer items-center gap-2 rounded-lg px-3 py-2 text-sm text-destructive-strong outline-none hover:bg-destructive-subtle "
              >
                <LogOut className="h-4 w-4" />
                Sign out
              </DropdownMenu.Item>
            </DropdownMenu.Content>
          </DropdownMenu.Portal>
        </DropdownMenu.Root>
      </div>
    </header>
  )
}
