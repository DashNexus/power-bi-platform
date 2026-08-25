import { NotificationPreferences } from '@/components/notifications/NotificationPreferences'

export const metadata = {
  title: 'Notification Settings',
}

export default function NotificationsSettingsPage() {
  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Notification Settings</h1>
        <p className="text-muted-foreground">Manage per-user notification preferences</p>
      </div>
      <NotificationPreferences />
    </div>
  )
}
