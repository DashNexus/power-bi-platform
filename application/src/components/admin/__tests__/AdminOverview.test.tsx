// @vitest-environment jsdom
/**
 * Tests for AdminOverview.
 *
 * Covers the thing the component decides rather than displays: which "needs
 * attention" items a given state produces. A link to a page whose feature is
 * off would 404, so the link set is behaviour, not decoration.
 */
import '@testing-library/jest-dom/vitest'
import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { AdminOverview, type AdminOverviewData } from '@/components/admin/AdminOverview'

const COUNT_KEYS = [
  'users_total',
  'users_active',
  'users_inactive',
  'users_with_mfa',
  'users_never_signed_in',
  'users_active_recently',
  'roles',
  'pending_invites',
  'expired_invites',
  'sso_providers_total',
  'sso_providers_enabled',
  'dashboards',
  'custom_pages',
  'warehouse_connections',
  'bi_connections',
  'pipeline_connections',
  'notification_groups',
  'dictionary_entries',
  'export_schedules',
  'audit_events_recent',
  'changes_recent',
] as const

function makeData(overrides: Partial<AdminOverviewData> = {}): AdminOverviewData {
  const counts = Object.fromEntries(COUNT_KEYS.map(key => [key, 0])) as Record<
    (typeof COUNT_KEYS)[number],
    number
  >

  return {
    org: { id: 1, name: 'Acme', app_name: 'Acme BI', audit_retention_days: 30 },
    counts: { ...counts, users_active: 4, users_with_mfa: 4, warehouse_connections: 2 },
    features: { total: 8, enabled: 2, disabled: 6, env_overrides: 0, enabled_keys: [] },
    auth: {
      totp_enabled: true,
      totp_required: true,
      email_otp_enabled: false,
      grace_period_days: 0,
    },
    recent_audit: [],
    recent_changes: [],
    active_window_days: 7,
    generated_at: new Date().toISOString(),
    ...overrides,
  }
}

describe('AdminOverview', () => {
  it('renders no attention alerts when nothing needs attention', () => {
    render(<AdminOverview data={makeData()} />)

    expect(screen.queryByText(/without MFA/)).not.toBeInTheDocument()
    expect(screen.queryByText('No warehouse connection')).not.toBeInTheDocument()
  })

  it('warns when no warehouse connection is configured', () => {
    const data = makeData()
    data.counts.warehouse_connections = 0

    render(<AdminOverview data={data} />)

    expect(screen.getByText('No warehouse connection')).toBeInTheDocument()
  })

  it('warns about active users lacking MFA only when MFA is not required', () => {
    const optional = makeData()
    optional.auth.totp_required = false
    optional.counts.users_with_mfa = 1

    render(<AdminOverview data={optional} />)

    expect(screen.getByText('3 active users without MFA')).toBeInTheDocument()
  })

  it('does not warn about MFA coverage when MFA is required', () => {
    const required = makeData()
    required.counts.users_with_mfa = 1

    render(<AdminOverview data={required} />)

    expect(screen.queryByText(/without MFA/)).not.toBeInTheDocument()
  })

  it('links only to pages this build ships', () => {
    render(<AdminOverview data={makeData()} />)

    const hrefs = screen.getAllByRole('link').map(link => link.getAttribute('href'))
    expect(hrefs).toContain('/admin/dashboards')
    expect(hrefs).toContain('/admin/data-dictionary')
    expect(hrefs).toContain('/admin/nav-config')
    // Removed features must not be linked — each would 404.
    expect(hrefs).not.toContain('/admin/datasets')
    expect(hrefs).not.toContain('/admin/timelines')
    expect(hrefs).not.toContain('/admin/tickets')
    expect(hrefs).not.toContain('/admin/org-settings')
    expect(hrefs).not.toContain('/admin/api-keys')
    expect(hrefs).not.toContain('/admin/features')
    expect(hrefs).not.toContain('/admin/notifications')
  })

  it('shows the audit retention window when one is set', () => {
    render(<AdminOverview data={makeData()} />)

    expect(screen.getByText('30 days')).toBeInTheDocument()
  })

  it('renders a recent change in the activity feed', () => {
    const data = makeData()
    data.recent_changes = [
      {
        id: 7,
        resource_type: 'custom_page',
        resource_id: 3,
        resource_name: 'Release notes',
        action: 'update',
        source: 'user',
        actor_name: 'Ada Lovelace',
        reverted_at: null,
        created_at: new Date().toISOString(),
      },
    ]

    render(<AdminOverview data={data} />)

    expect(screen.getByText(/Release notes/)).toBeInTheDocument()
  })

  it('explains the empty activity feeds', () => {
    render(<AdminOverview data={makeData()} />)

    expect(screen.getByText('No activity recorded')).toBeInTheDocument()
    expect(screen.getByText('Nothing changed yet')).toBeInTheDocument()
  })
})
