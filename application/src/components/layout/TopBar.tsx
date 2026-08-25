'use client'

/**
 * Application top bar.
 *
 * Shows org branding, a command palette trigger, and a user avatar dropdown.
 * Receives session and org settings from the server layout — no client-side
 * data fetching needed.
 */
import type { Session } from 'next-auth'
import { signOut } from 'next-auth/react'
import { Search, LogOut, User, Settings, Sun, Moon, Monitor, LayoutGrid } from 'lucide-react'
import { useTheme } from 'next-themes'
import * as DropdownMenu from '@radix-ui/react-dropdown-menu'
import { cn } from '@/lib/utils'
import { Avatar } from '@/components/ui'
import { Brand } from '@/components/ui/Brand'

interface OrgSettings {
  org_id: number
  name: string
  logo_url: string | null
  primary_color: string | null
  custom_domain: string | null
}

interface TopBarProps {
  session: Session
  orgSettings: OrgSettings | null
  onSearchOpen?: () => void
}

function ThemeToggle() {
  const { theme, setTheme } = useTheme()

  return (
    <DropdownMenu.Root>
      <DropdownMenu.Trigger asChild>
        <button
          type="button"
          aria-label="Toggle theme"
          className="rounded-lg p-1.5 text-muted-foreground hover:bg-accent hover:text-foreground transition-colors"
        >
          <Sun className="h-4 w-4 dark:hidden" />
          <Moon className="h-4 w-4 hidden dark:block" />
        </button>
      </DropdownMenu.Trigger>
      <DropdownMenu.Portal>
        <DropdownMenu.Content
          align="end"
          sideOffset={8}
          className="z-50 min-w-[140px] rounded-xl border border-border bg-card p-1.5 shadow-lg"
        >
          {[
            { value: 'light', label: 'Light', icon: Sun },
            { value: 'dark', label: 'Dark', icon: Moon },
            { value: 'system', label: 'System', icon: Monitor },
          ].map(({ value, label, icon: Icon }) => (
            <DropdownMenu.Item
              key={value}
              onSelect={() => setTheme(value)}
              className={cn(
                'flex items-center gap-2 rounded-lg px-3 py-2 text-sm cursor-pointer outline-none',
                theme === value
                  ? 'bg-primary-subtle text-info-strong font-medium'
                  : 'text-foreground hover:bg-accent ',
              )}
            >
              <Icon className="h-3.5 w-3.5" />
              {label}
            </DropdownMenu.Item>
          ))}
        </DropdownMenu.Content>
      </DropdownMenu.Portal>
    </DropdownMenu.Root>
  )
}

export function TopBar({ session, orgSettings, onSearchOpen }: TopBarProps) {
  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-card px-4 shrink-0">
      {/* Left: brand (shown on mobile where the sidebar is hidden) */}
      <div className="flex items-center gap-3 md:hidden">
        <Brand name={orgSettings?.name} logoUrl={orgSettings?.logo_url} size="sm" />
      </div>

      {/* Right: theme toggle + search + user menu */}
      <div className="ml-auto flex items-center gap-3">
        <ThemeToggle />

        {/* Command palette trigger */}
        <button
          type="button"
          aria-label="Open search"
          onClick={onSearchOpen}
          className={cn(
            'flex items-center gap-2 rounded-lg border border-border ',
            'bg-muted ',
            'px-3 py-1.5 text-sm text-muted-foreground ',
            'hover:bg-accent hover:text-foreground ',
            'transition-colors duration-150',
          )}
        >
          <Search className="h-3.5 w-3.5" />
          <span className="hidden sm:inline">Search</span>
          <kbd className="hidden sm:inline-block ml-1 rounded bg-secondary px-1.5 py-0.5 text-xs text-muted-foreground ">
            ⌘K
          </kbd>
        </button>

        {/* User dropdown */}
        <DropdownMenu.Root>
          <DropdownMenu.Trigger asChild>
            <button
              type="button"
              aria-label="User menu"
              className="focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 rounded-full"
            >
              <Avatar
                name={session.user.name}
                email={session.user.email}
                avatarUrl={session.user.avatar_url}
              />
            </button>
          </DropdownMenu.Trigger>

          <DropdownMenu.Portal>
            <DropdownMenu.Content
              align="end"
              sideOffset={8}
              className="z-50 min-w-[200px] rounded-xl border border-border bg-card p-1.5 shadow-lg animate-in fade-in slide-in-from-top-2 duration-100"
            >
              {/* User info header */}
              <div className="px-3 py-2 mb-1">
                <p className="text-sm font-medium text-foreground truncate">
                  {session.user.name ?? session.user.email}
                </p>
                <p className="text-xs text-muted-foreground truncate">{session.user.email}</p>
              </div>

              <DropdownMenu.Separator className="my-1 h-px bg-muted" />

              <DropdownMenu.Item asChild>
                <a
                  href="/home"
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent cursor-pointer outline-none"
                >
                  <LayoutGrid className="h-4 w-4" />
                  Portal
                </a>
              </DropdownMenu.Item>

              <DropdownMenu.Item asChild>
                <a
                  href="/settings"
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent cursor-pointer outline-none"
                >
                  <Settings className="h-4 w-4" />
                  Settings
                </a>
              </DropdownMenu.Item>

              <DropdownMenu.Item asChild>
                <a
                  href="/settings/security"
                  className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-foreground hover:bg-accent cursor-pointer outline-none"
                >
                  <User className="h-4 w-4" />
                  Profile &amp; Security
                </a>
              </DropdownMenu.Item>

              <DropdownMenu.Separator className="my-1 h-px bg-muted" />

              <DropdownMenu.Item
                onSelect={() => signOut({ callbackUrl: '/login' })}
                className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-destructive-strong hover:bg-destructive-subtle cursor-pointer outline-none"
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
