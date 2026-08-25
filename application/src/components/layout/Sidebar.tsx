'use client'

/**
 * Application navigation sidebar.
 *
 * Core admin items (Users, Roles, Dashboards, Auth, Pipeline Monitor, etc.)
 * are always visible to admin users. Optional features (Chat, Exports, Lineage,
 * Governance, Backups, Retention) are gated by feature flags.
 *
 * Items support drag-to-reorder within their own section (main or admin) using
 * native HTML5 drag events. The custom order is persisted per browser in
 * localStorage ('sidebar-order:main' / 'sidebar-order:admin') as arrays of
 * hrefs, so feature-gated items that are currently hidden never corrupt it.
 *
 * When `collapsed` is true the sidebar renders in icons-only mode (w-16) and
 * dragging is disabled.
 */
import { useState } from 'react'
import Link from 'next/link'
import {
  LayoutDashboard,
  Download,
  FileText,
  Settings,
  Users,
  ShieldCheck,
  Database,
  ScrollText,
  History,
  UserCog,
  Layers,
  PanelTop,
  NotebookText,
  Home,
  ChevronLeft,
  ChevronRight,
  GripVertical,
  Workflow,
  BarChart3,
  Megaphone,
  Menu,
  Gauge,
} from 'lucide-react'
import { hasRole } from '@/lib/permissions'
import { cn } from '@/lib/utils'

interface SidebarProps {
  role: string
  features: Record<string, boolean>
  collapsed?: boolean
  onToggleCollapse?: () => void
}

interface NavItem {
  label: string
  href: string
  icon: React.ComponentType<{ className?: string }>
}

type Section = 'main' | 'admin'

const ORDER_STORAGE_KEYS: Record<Section, string> = {
  main: 'sidebar-order:main',
  admin: 'sidebar-order:admin',
}

function loadSavedOrder(section: Section): string[] {
  // Window guard: this runs in a useState initializer, which Next.js also
  // executes during SSR/prerender where localStorage does not exist.
  if (typeof window === 'undefined') return []
  try {
    const raw = window.localStorage.getItem(ORDER_STORAGE_KEYS[section])
    const parsed: unknown = raw ? JSON.parse(raw) : []
    return Array.isArray(parsed) ? parsed.filter((h): h is string => typeof h === 'string') : []
  } catch {
    return []
  }
}

/**
 * Apply a saved href order to the default item list with a stable merge.
 *
 * Items whose href appears in the saved order keep that order. Items missing
 * from it (new features, newly-enabled flags) are inserted after their nearest
 * default predecessor already present, preserving their default relative
 * position. Saved hrefs with no matching item (hidden features) are ignored.
 */
function applyOrder(items: NavItem[], saved: string[]): NavItem[] {
  if (saved.length === 0) return items

  const byHref = new Map(items.map(item => [item.href, item]))
  const ordered = saved
    .filter(href => byHref.has(href))
    .map(href => byHref.get(href) as NavItem)
  const placed = new Set(ordered.map(item => item.href))

  items.forEach((item, defaultIdx) => {
    if (placed.has(item.href)) return
    let insertAt = 0
    for (let j = defaultIdx - 1; j >= 0; j--) {
      const prevIdx = ordered.findIndex(o => o.href === items[j].href)
      if (prevIdx !== -1) {
        insertAt = prevIdx + 1
        break
      }
    }
    ordered.splice(insertAt, 0, item)
    placed.add(item.href)
  })

  return ordered
}

function NavLink({
  href,
  icon: Icon,
  label,
  collapsed,
}: NavItem & { collapsed?: boolean }) {
  return (
    <Link
      href={href}
      title={collapsed ? label : undefined}
      className={cn(
        'flex items-center rounded-lg px-3 py-2 text-sm font-medium',
        'text-muted-foreground ',
        'hover:bg-accent ',
        'hover:text-foreground ',
        'transition-colors duration-150',
        collapsed ? 'justify-center gap-0' : 'gap-3',
      )}
    >
      <Icon className="h-4 w-4 shrink-0" />
      {!collapsed && label}
    </Link>
  )
}

export function Sidebar({ role, features, collapsed = false, onToggleCollapse }: SidebarProps) {
  const isAdmin = hasRole(role, 'admin')

  const [mainOrder, setMainOrder] = useState<string[]>(() => loadSavedOrder('main'))
  const [adminOrder, setAdminOrder] = useState<string[]>(() => loadSavedOrder('admin'))
  const [dragged, setDragged] = useState<{ section: Section; href: string } | null>(null)
  const [dropTarget, setDropTarget] = useState<string | null>(null)

  const mainItems: NavItem[] = [
    { label: 'Home', href: '/home', icon: Home },
    ...(features['dashboards']
      ? [{ label: 'Dashboards', href: '/dashboard', icon: LayoutDashboard }]
      : []),
    ...(features['custom_pages'] ? [{ label: 'Pages', href: '/pages', icon: FileText }] : []),
    ...(features['governance']
      ? [{ label: 'Data Dictionary', href: '/data-dicts', icon: NotebookText }]
      : []),
    ...(features['pipelines']
      ? [{ label: 'Data Pipelines', href: '/pipelines', icon: Workflow }]
      : []),
    ...(features['exports'] ? [{ label: 'Data Exports', href: '/exports', icon: Download }] : []),
    { label: 'Settings', href: '/settings', icon: Settings },
  ]

  const adminItems: NavItem[] = isAdmin
    ? [
        { label: 'Overview', href: '/admin', icon: Gauge },
        { label: 'Users', href: '/admin/users', icon: Users },
        { label: 'Roles', href: '/admin/roles', icon: UserCog },
        { label: 'Auth Configuration', href: '/admin/auth-config', icon: ShieldCheck },
        { label: 'Navigation', href: '/admin/nav-config', icon: Menu },
        { label: 'Dashboards', href: '/admin/dashboards', icon: Layers },
        ...(features['custom_pages']
          ? [{ label: 'Custom Pages', href: '/admin/pages', icon: PanelTop }]
          : []),
        { label: 'BI Connections', href: '/admin/bi-connections', icon: BarChart3 },
        { label: 'Warehouses', href: '/admin/warehouses', icon: Database },
        { label: 'Data Dictionary', href: '/admin/data-dictionary', icon: NotebookText },
        { label: 'Data Pipelines', href: '/admin/data-pipelines', icon: Workflow },
        { label: 'Notification Groups', href: '/admin/notification-groups', icon: Megaphone },
        { label: 'Audit Log', href: '/admin/audit', icon: ScrollText },
        { label: 'Change History', href: '/admin/changes', icon: History },
      ]
    : []

  const orderedMain = applyOrder(mainItems, mainOrder)
  const orderedAdmin = applyOrder(adminItems, adminOrder)

  function handleDrop(section: Section, targetHref: string) {
    if (!dragged || dragged.section !== section || dragged.href === targetHref) return

    const hrefs = (section === 'main' ? orderedMain : orderedAdmin).map(item => item.href)
    const from = hrefs.indexOf(dragged.href)
    if (from === -1) return
    hrefs.splice(from, 1)
    // Insert above the hovered item, matching the border-top indicator
    hrefs.splice(hrefs.indexOf(targetHref), 0, dragged.href)

    if (section === 'main') setMainOrder(hrefs)
    else setAdminOrder(hrefs)
    try {
      window.localStorage.setItem(ORDER_STORAGE_KEYS[section], JSON.stringify(hrefs))
    } catch {
      // Persisting is best-effort; the in-memory order still applies
    }
  }

  function renderDraggableItem(item: NavItem, section: Section) {
    const isDropTarget =
      dropTarget === item.href && dragged?.section === section && dragged.href !== item.href

    return (
      <div
        key={item.href}
        draggable={!collapsed}
        onDragStart={e => {
          // setData is required for Firefox to initiate the drag at all
          e.dataTransfer.setData('text/plain', item.href)
          e.dataTransfer.effectAllowed = 'move'
          setDragged({ section, href: item.href })
        }}
        onDragOver={e => {
          if (dragged && dragged.section === section && dragged.href !== item.href) {
            e.preventDefault()
            e.dataTransfer.dropEffect = 'move'
            setDropTarget(item.href)
          }
        }}
        onDragLeave={() => {
          setDropTarget(current => (current === item.href ? null : current))
        }}
        onDrop={e => {
          e.preventDefault()
          handleDrop(section, item.href)
          setDragged(null)
          setDropTarget(null)
        }}
        onDragEnd={() => {
          setDragged(null)
          setDropTarget(null)
        }}
        className={cn(
          'group relative border-t-2',
          isDropTarget ? 'border-primary/60' : 'border-transparent',
        )}
      >
        <NavLink {...item} collapsed={collapsed} />
        {!collapsed && (
          <GripVertical
            className={cn(
              'pointer-events-none absolute right-2 top-1/2 h-3.5 w-3.5 -translate-y-1/2',
              'text-muted-foreground opacity-0 group-hover:opacity-100',
              'transition-opacity duration-150',
            )}
          />
        )}
      </div>
    )
  }

  return (
    // Only the item list scrolls. Scrolling the whole nav pushed the collapse
    // toggle below the fold as soon as the admin list outgrew the viewport.
    <nav className="flex h-full flex-col overflow-hidden">
      <div
        className={cn(
          'min-h-0 flex-1 space-y-0 overflow-y-auto overscroll-contain p-3',
          collapsed && 'p-2',
        )}
      >
        {/* Main navigation */}
        <div className="space-y-0.5">
          {orderedMain.map(item => renderDraggableItem(item, 'main'))}
        </div>

        {/* Admin section */}
        {orderedAdmin.length > 0 && (
          <div className="mt-6 space-y-0.5 border-t border-border pt-4">
            {!collapsed && (
              <p className="mb-2 px-3 text-xs font-semibold uppercase tracking-wider text-muted-foreground ">
                Administration
              </p>
            )}
            {orderedAdmin.map(item => renderDraggableItem(item, 'admin'))}
          </div>
        )}
      </div>

      {/* Collapse toggle — pinned; sits outside the scroll area above. */}
      {onToggleCollapse && (
        <div className="shrink-0 border-t border-border bg-card p-2">
          <button
            type="button"
            onClick={onToggleCollapse}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className={cn(
              'flex w-full items-center rounded-lg px-3 py-2 text-sm font-medium',
              'text-muted-foreground ',
              'hover:bg-accent ',
              'hover:text-foreground ',
              'transition-colors',
              collapsed && 'justify-center px-2',
            )}
          >
            {collapsed ? (
              <ChevronRight className="h-4 w-4 shrink-0" />
            ) : (
              <>
                <ChevronLeft className="h-4 w-4 shrink-0 mr-2" />
                Collapse
              </>
            )}
          </button>
        </div>
      )}
    </nav>
  )
}
