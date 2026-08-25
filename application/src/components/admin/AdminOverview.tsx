/**
 * The /admin landing page: what this organisation currently holds, how it is
 * configured, and what changed recently.
 *
 * Everything rendered here comes from one request (`GET /admin/overview`). The
 * "needs attention" list is derived in this component rather than server-side,
 * so a threshold can be re-worded or linked differently without an API change —
 * and each item links to the page that resolves it, because a count nobody can
 * act on is decoration.
 */
import Link from 'next/link'
import {
  ScrollText,
  Activity,
  BarChart3,
  Megaphone,
  Menu,
  Bot,
  Database,
  History,
  Layers,
  NotebookText,
  PanelTop,
  ShieldCheck,
  ToggleLeft,
  UserCog,
  Users,
  Workflow,
} from 'lucide-react'
import {
  Alert,
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  PageHeader,
} from '@/components/ui'
import { cn } from '@/lib/utils'

interface OverviewCounts {
  users_total: number
  users_active: number
  users_inactive: number
  users_with_mfa: number
  users_never_signed_in: number
  users_active_recently: number
  roles: number
  pending_invites: number
  expired_invites: number
  sso_providers_total: number
  sso_providers_enabled: number
  dashboards: number
  custom_pages: number
  warehouse_connections: number
  bi_connections: number
  pipeline_connections: number
  notification_groups: number
  dictionary_entries: number
  export_schedules: number
  audit_events_recent: number
  changes_recent: number
}

interface AuditEntry {
  id: number
  action: string
  resource_type: string | null
  resource_name: string | null
  user_name: string | null
  created_at: string
}

interface ChangeEntry {
  id: number
  resource_type: string
  resource_id: number | null
  resource_name: string | null
  action: string
  source: string
  actor_name: string | null
  reverted_at: string | null
  created_at: string
}

export interface AdminOverviewData {
  org: {
    id: number
    name: string | null
    slug?: string | null
    app_name?: string | null
    audit_retention_days?: number | null
  }
  counts: OverviewCounts
  features: {
    total: number
    enabled: number
    disabled: number
    env_overrides: number
    enabled_keys: string[]
  }
  auth: {
    totp_enabled: boolean
    totp_required: boolean
    email_otp_enabled: boolean
    grace_period_days: number
  }
  recent_audit: AuditEntry[]
  recent_changes: ChangeEntry[]
  active_window_days: number
  generated_at: string
}

interface AdminOverviewProps {
  data: AdminOverviewData
}

interface AttentionItem {
  tone: 'warning' | 'info'
  title: string
  detail: string
  href: string
  action: string
}

function formatRelative(iso: string): string {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  if (mins < 1440) return `${Math.floor(mins / 60)}h ago`
  return `${Math.floor(mins / 1440)}d ago`
}

function plural(count: number, singular: string, pluralForm = `${singular}s`): string {
  return count === 1 ? singular : pluralForm
}

/** Build the act-on-this list. Ordered most urgent first; empty is the good case. */
function attentionItems(data: AdminOverviewData): AttentionItem[] {
  const { counts, auth } = data
  const items: AttentionItem[] = []

  if (counts.warehouse_connections === 0) {
    items.push({
      tone: 'warning',
      title: 'No warehouse connection',
      detail: 'Data queries, exports, and the data dictionary all need one.',
      href: '/admin/warehouses',
      action: 'Add a connection',
    })
  }

  if (!auth.totp_required && counts.users_with_mfa < counts.users_active) {
    const without = counts.users_active - counts.users_with_mfa
    items.push({
      tone: 'warning',
      title: `${without} active ${plural(without, 'user')} without MFA`,
      detail: 'Two-factor authentication is available but not required.',
      href: '/admin/auth-config/mfa',
      action: 'Review MFA settings',
    })
  }

  if (counts.expired_invites > 0) {
    items.push({
      tone: 'info',
      title: `${counts.expired_invites} ${plural(counts.expired_invites, 'invitation')} expired`,
      detail: 'The link no longer works; send a fresh invitation.',
      href: '/admin/users',
      action: 'Manage users',
    })
  }

  if (counts.users_never_signed_in > 0) {
    items.push({
      tone: 'info',
      title: `${counts.users_never_signed_in} ${plural(counts.users_never_signed_in, 'account')} never signed in`,
      detail: 'Active accounts with no first sign-in recorded.',
      href: '/admin/users',
      action: 'Manage users',
    })
  }

  return items
}

interface StatTileProps {
  label: string
  value: number
  hint: string
  href: string
  icon: React.ComponentType<{ className?: string }>
}

function StatTile({ label, value, hint, href, icon: Icon }: StatTileProps) {
  return (
    <Card interactive className="p-0">
      <Link href={href} className="flex h-full items-start gap-3 px-4 py-4">
        <span className="rounded-lg bg-primary-subtle p-2 text-info-strong">
          <Icon className="h-4 w-4" aria-hidden />
        </span>
        <span className="min-w-0">
          <span className="block text-xs font-medium uppercase tracking-wide text-muted-foreground">
            {label}
          </span>
          <span className="block text-2xl font-semibold tabular-nums text-foreground">
            {value.toLocaleString()}
          </span>
          <span className="mt-0.5 block text-xs text-muted-foreground">{hint}</span>
        </span>
      </Link>
    </Card>
  )
}

interface MetricProps {
  label: string
  value: React.ReactNode
  href?: string
  muted?: boolean
}

/** One label/value line inside a section card. Links when the row has a home. */
function Metric({ label, value, href, muted }: MetricProps) {
  const row = (
    <>
      <dt className={cn('truncate text-sm', muted ? 'text-muted-foreground' : 'text-foreground')}>
        {label}
      </dt>
      <dd className="shrink-0 text-sm font-medium tabular-nums text-foreground">{value}</dd>
    </>
  )

  if (!href) {
    return <div className="flex items-baseline justify-between gap-3 py-2">{row}</div>
  }

  return (
    <Link
      href={href}
      className="flex items-baseline justify-between gap-3 rounded-md py-2 transition-colors hover:text-primary"
    >
      {row}
    </Link>
  )
}

interface SectionProps {
  title: string
  icon: React.ComponentType<{ className?: string }>
  children: React.ReactNode
}

function Section({ title, icon: Icon, children }: SectionProps) {
  return (
    <Card>
      <CardHeader className="flex-row items-center gap-2">
        <Icon className="h-4 w-4 text-muted-foreground" aria-hidden />
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      <CardContent className="py-2">
        <dl className="divide-y divide-border">{children}</dl>
      </CardContent>
    </Card>
  )
}

export function AdminOverview({ data }: AdminOverviewProps) {
  const { counts, features, auth, org } = data
  const attention = attentionItems(data)
  const windowLabel = `last ${data.active_window_days} days`

  return (
    <div className="space-y-6">
      <PageHeader
        title="Admin overview"
        description={`${org.name ?? 'This organisation'} — configuration, content, and activity at a glance.`}
        actions={
          <Badge tone="neutral" title={new Date(data.generated_at).toLocaleString()}>
            As of {formatRelative(data.generated_at)}
          </Badge>
        }
      />

      {attention.length > 0 && (
        <div className="space-y-2">
          {attention.map(item => (
            <Alert key={item.title} tone={item.tone} title={item.title}>
              {item.detail}{' '}
              <Link href={item.href} className="font-medium text-primary hover:underline">
                {item.action}
              </Link>
            </Alert>
          ))}
        </div>
      )}

      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatTile
          label="Active users"
          value={counts.users_active}
          hint={`${counts.users_active_recently} signed in in the ${windowLabel}`}
          href="/admin/users"
          icon={Users}
        />
        <StatTile
          label="Dashboards"
          value={counts.dashboards}
          hint={`${counts.custom_pages} custom ${plural(counts.custom_pages, 'page')}`}
          href="/admin/dashboards"
          icon={Layers}
        />
        <StatTile
          label="Connections"
          value={counts.warehouse_connections + counts.bi_connections + counts.pipeline_connections}
          hint={`${counts.warehouse_connections} warehouse, ${counts.bi_connections} BI, ${counts.pipeline_connections} pipeline`}
          href="/admin/warehouses"
          icon={Database}
        />
        <StatTile
          label={`Changes (${windowLabel})`}
          value={counts.changes_recent}
          hint={`${counts.audit_events_recent} audit events`}
          href="/admin/changes"
          icon={History}
        />
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Section title="People & access" icon={UserCog}>
          <Metric label="Users" value={counts.users_total} href="/admin/users" />
          <Metric label="Deactivated" value={counts.users_inactive} href="/admin/users" muted />
          <Metric
            label="MFA enabled"
            value={`${counts.users_with_mfa} of ${counts.users_active}`}
            href="/admin/auth-config/mfa"
          />
          <Metric
            label="MFA required"
            value={
              auth.totp_required ? (
                <Badge tone="success">Required</Badge>
              ) : (
                <Badge tone="warning">Optional</Badge>
              )
            }
            href="/admin/auth-config/mfa"
          />
          <Metric label="Roles" value={counts.roles} href="/admin/roles" />
          <Metric label="Pending invitations" value={counts.pending_invites} href="/admin/users" />
          <Metric
            label="SSO providers enabled"
            value={`${counts.sso_providers_enabled} of ${counts.sso_providers_total}`}
            href="/admin/auth-config"
          />
        </Section>

        <Section title="Content" icon={PanelTop}>
          <Metric label="Dashboards" value={counts.dashboards} href="/admin/dashboards" />
          <Metric label="Custom pages" value={counts.custom_pages} href="/admin/pages" />
          <Metric
            label="Export schedules"
            value={counts.export_schedules}
            href="/exports"
          />
        </Section>

        <Section title="Data platform" icon={Workflow}>
          <Metric
            label="Warehouse connections"
            value={counts.warehouse_connections}
            href="/admin/warehouses"
          />
          <Metric label="BI connections" value={counts.bi_connections} href="/admin/bi-connections" />
          <Metric
            label="Pipeline connections"
            value={counts.pipeline_connections}
            href="/admin/data-pipelines"
          />
          <Metric
            label="Dictionary entries"
            value={counts.dictionary_entries}
            href="/admin/data-dictionary"
          />
          <Metric
            label="Notification groups"
            value={counts.notification_groups}
            href="/admin/notification-groups"
          />
        </Section>
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div className="flex items-center gap-2">
              <Activity className="h-4 w-4 text-muted-foreground" aria-hidden />
              <CardTitle>Recent activity</CardTitle>
            </div>
            <Link href="/admin/audit" className="text-xs font-medium text-primary hover:underline">
              Audit log
            </Link>
          </CardHeader>
          <CardContent className={data.recent_audit.length === 0 ? '' : 'py-2'}>
            {data.recent_audit.length === 0 ? (
              <EmptyState
                title="No activity recorded"
                description="Sign-ins, dashboard views, and data queries appear here once users start working."
              />
            ) : (
              <ul className="divide-y divide-border">
                {data.recent_audit.map(entry => (
                  <li key={entry.id} className="flex items-baseline justify-between gap-3 py-2">
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-foreground">
                        {entry.action}
                        {entry.resource_name && (
                          <span className="text-muted-foreground"> · {entry.resource_name}</span>
                        )}
                      </span>
                      <span className="text-xs text-muted-foreground">
                        {entry.user_name ?? 'System'}
                      </span>
                    </span>
                    <span
                      className="shrink-0 text-xs text-muted-foreground"
                      title={new Date(entry.created_at).toLocaleString()}
                    >
                      {formatRelative(entry.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex-row items-center justify-between">
            <div className="flex items-center gap-2">
              <History className="h-4 w-4 text-muted-foreground" aria-hidden />
              <CardTitle>Recent changes</CardTitle>
            </div>
            <Link href="/admin/changes" className="text-xs font-medium text-primary hover:underline">
              Change history
            </Link>
          </CardHeader>
          <CardContent className={data.recent_changes.length === 0 ? '' : 'py-2'}>
            {data.recent_changes.length === 0 ? (
              <EmptyState
                title="Nothing changed yet"
                description="Creating, editing, or deleting a resource records a revertible entry here."
              />
            ) : (
              <ul className="divide-y divide-border">
                {data.recent_changes.map(entry => (
                  <li key={entry.id} className="flex items-baseline justify-between gap-3 py-2">
                    <span className="min-w-0">
                      <span className="block truncate text-sm text-foreground">
                        {entry.action} {entry.resource_type.replace(/_/g, ' ')}
                        {entry.resource_name && (
                          <span className="text-muted-foreground"> · {entry.resource_name}</span>
                        )}
                      </span>
                      <span className="flex items-center gap-1.5 text-xs text-muted-foreground">
                        {entry.source === 'ai' && (
                          <Badge tone="assistant">
                            <Bot aria-hidden />
                            AI
                          </Badge>
                        )}
                        {entry.actor_name ?? 'System'}
                        {entry.reverted_at && <Badge tone="neutral">Reverted</Badge>}
                      </span>
                    </span>
                    <span
                      className="shrink-0 text-xs text-muted-foreground"
                      title={new Date(entry.created_at).toLocaleString()}
                    >
                      {formatRelative(entry.created_at)}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex-row items-center justify-between">
          <div className="flex items-center gap-2">
            <ToggleLeft className="h-4 w-4 text-muted-foreground" aria-hidden />
            <CardTitle>Platform configuration</CardTitle>
          </div>
        </CardHeader>
        <CardContent className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Features enabled
            </p>
            <p className="text-lg font-semibold tabular-nums text-foreground">
              {features.enabled} of {features.total}
            </p>
            <p className="text-xs text-muted-foreground">
              {features.env_overrides === 0
                ? 'All controlled from the database'
                : `${features.env_overrides} forced by environment ${plural(features.env_overrides, 'variable')}`}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Audit retention
            </p>
            <p className="text-lg font-semibold tabular-nums text-foreground">
              {org.audit_retention_days ? `${org.audit_retention_days} days` : 'Unlimited'}
            </p>
            <p className="text-xs text-muted-foreground">
              {counts.audit_events_recent.toLocaleString()} events in the {windowLabel} ·{' '}
              <Link href="/admin/audit" className="text-primary hover:underline">
                Audit log
              </Link>
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Scheduled exports
            </p>
            <p className="text-lg font-semibold tabular-nums text-foreground">
              {counts.export_schedules}
            </p>
            <p className="text-xs text-muted-foreground">
              {counts.notification_groups} notification {plural(counts.notification_groups, 'group')}
            </p>
          </div>
          <div>
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Data dictionary
            </p>
            <p className="text-lg font-semibold tabular-nums text-foreground">
              {counts.dictionary_entries.toLocaleString()}
            </p>
            <p className="text-xs text-muted-foreground">
              documented {plural(counts.dictionary_entries, 'column')} ·{' '}
              <Link href="/admin/data-dictionary" className="text-primary hover:underline">
                Open
              </Link>
            </p>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Jump to</CardTitle>
        </CardHeader>
        <CardContent className="flex flex-wrap gap-2">
          {[
            { label: 'Users', href: '/admin/users', icon: Users },
            { label: 'Roles', href: '/admin/roles', icon: UserCog },
            { label: 'Auth configuration', href: '/admin/auth-config', icon: ShieldCheck },
            { label: 'Navigation', href: '/admin/nav-config', icon: Menu },
            { label: 'Dashboards', href: '/admin/dashboards', icon: Layers },
            { label: 'Custom pages', href: '/admin/pages', icon: PanelTop },
            { label: 'Warehouses', href: '/admin/warehouses', icon: Database },
            { label: 'BI connections', href: '/admin/bi-connections', icon: BarChart3 },
            { label: 'Data pipelines', href: '/admin/data-pipelines', icon: Workflow },
            { label: 'Data dictionary', href: '/admin/data-dictionary', icon: NotebookText },
            { label: 'Notification groups', href: '/admin/notification-groups', icon: Megaphone },
            { label: 'Audit log', href: '/admin/audit', icon: ScrollText },
            { label: 'Change history', href: '/admin/changes', icon: History },
          ].map(link => (
            <Link
              key={link.href}
              href={link.href}
              className="inline-flex items-center gap-2 rounded-lg border border-border bg-card px-3 py-1.5 text-sm text-foreground transition-colors hover:border-primary/50 hover:bg-accent"
            >
              <link.icon className="h-4 w-4 text-muted-foreground" aria-hidden />
              {link.label}
            </Link>
          ))}
        </CardContent>
      </Card>
    </div>
  )
}
