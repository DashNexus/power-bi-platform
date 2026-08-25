import Link from 'next/link'
import { Shield, Bell, User } from 'lucide-react'

export const metadata = {
  title: 'Settings',
}

interface SettingsLink {
  href: string
  icon: React.ComponentType<{ className?: string }>
  title: string
  description: string
}

const settingsLinks: SettingsLink[] = [
  {
    href: '/settings/security',
    icon: Shield,
    title: 'Security',
    description: 'Manage two-factor authentication and active sessions.',
  },
  {
    href: '/settings/notifications',
    icon: Bell,
    title: 'Notifications',
    description: 'Configure email, Slack, and Teams notification preferences.',
  },
  {
    href: '/settings/profile',
    icon: User,
    title: 'Profile',
    description: 'Update your display name and account details.',
  },
]

export default function SettingsPage() {
  return (
    <div>
      <div className="mb-6">
        <h1 className="text-2xl font-semibold text-foreground">Settings</h1>
        <p className="mt-1 text-sm text-muted-foreground">Manage your account and preferences.</p>
      </div>

      <div className="space-y-3">
        {settingsLinks.map(item => (
          <Link
            key={item.href}
            href={item.href}
            className="flex items-center gap-4 rounded-xl border border-border bg-card p-4 hover:border-primary/50 hover:shadow-sm transition-all duration-150"
          >
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg bg-muted">
              <item.icon className="h-5 w-5 text-muted-foreground" />
            </div>
            <div>
              <p className="text-sm font-medium text-foreground">{item.title}</p>
              <p className="text-xs text-muted-foreground">{item.description}</p>
            </div>
          </Link>
        ))}
      </div>
    </div>
  )
}
