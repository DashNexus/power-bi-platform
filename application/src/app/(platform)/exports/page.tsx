'use client'

/**
 * Data Exports page.
 *
 * Two tabs: SQL Reports (the definitions) and Run History (every execution and
 * its result).
 *
 * There was a third, Schedules, backed by export_schedules rows with no query.
 * It collected a name, a cron, a format and a delivery target but nothing that
 * said *what to export*, so nothing could ever run one. A report with a cron
 * expression is that feature, done properly.
 */
import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { Plus } from 'lucide-react'
import { ExportHistoryTable } from '@/components/exports/ExportHistoryTable'
import { ReportDialog } from '@/components/exports/ReportDialog'
import { ReportsTable } from '@/components/exports/ReportsTable'
import type { Report } from '@/components/exports/types'
import { hasRole } from '@/lib/permissions'
import { Button } from '@/components/ui/Button'
import { Card } from '@/components/ui/Card'
import { PageHeader } from '@/components/ui/PageHeader'
import { Tabs, type TabItem } from '@/components/ui/Tabs'
import { APP_NAME } from '@/components/ui/Brand'

type Tab = 'reports' | 'history'

const TABS: ReadonlyArray<TabItem<Tab>> = [
  { id: 'reports', label: 'SQL Reports' },
  { id: 'history', label: 'Run History' },
]

export default function ExportsPage() {
  const { data: session } = useSession()
  const [activeTab, setActiveTab] = useState<Tab>('reports')
  // null = closed; undefined = open on a new report; a Report = open on that one.
  const [editing, setEditing] = useState<Report | null | undefined>(null)
  const [refreshToken, setRefreshToken] = useState(0)

  useEffect(() => {
    document.title = `Data Exports — ${APP_NAME}`
  }, [])

  const canUseOperations = hasRole(session?.user?.role, 'admin')

  return (
    <div className="space-y-6">
      <PageHeader
        title="Data Exports"
        description="Run read-only queries against a warehouse connection or the operations database, on a schedule or on demand."
        actions={
          activeTab === 'reports' ? (
            <Button onClick={() => setEditing(undefined)}>
              <Plus aria-hidden />
              New Report
            </Button>
          ) : null
        }
      />

      {editing !== null && (
        <ReportDialog
          report={editing}
          canUseOperations={canUseOperations}
          onClose={() => setEditing(null)}
          onSaved={() => setRefreshToken(n => n + 1)}
        />
      )}

      <Card className="overflow-hidden">
        <Tabs
          tabs={TABS}
          active={activeTab}
          onChange={setActiveTab}
          aria-label="Export views"
          className="px-2"
        />
        <div className="p-6">
          {activeTab === 'reports' && (
            <ReportsTable refreshToken={refreshToken} onEdit={setEditing} />
          )}
          {activeTab === 'history' && <ExportHistoryTable />}
        </div>
      </Card>
    </div>
  )
}
