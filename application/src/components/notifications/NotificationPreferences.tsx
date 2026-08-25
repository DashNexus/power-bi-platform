'use client'

/**
 * Notification preferences table with channel x event toggle switches.
 *
 * Fetches from GET /notifications/prefs and allows toggling each combination.
 */
import { useEffect, useState } from 'react'
import { useSession } from 'next-auth/react'
import { createClientFetch } from '@/lib/api'

interface NotificationPref {
  id: number
  channel: string
  event_type: string
  enabled: boolean
  config: Record<string, unknown> | null
}

const CHANNELS = ['email', 'slack', 'teams', 'gchat', 'sms'] as const
const EVENT_TYPES = [
  'pipeline_failure',
  'pipeline_success',
  'export_ready',
  'export_failed',
  'data_freshness',
  'pipeline_idle',
  'backup_complete',
  'backup_failed',
] as const

export function NotificationPreferences() {
  const { data: session } = useSession()
  const [prefs, setPrefs] = useState<NotificationPref[]>([])
  const [loading, setLoading] = useState(true)
  const [updated, setUpdated] = useState<Map<string, boolean>>(new Map())

  useEffect(() => {
    const token = session?.user?.access_token
    if (!token) return
    const apiFetch = createClientFetch(token)
    apiFetch<NotificationPref[]>('/notifications/prefs')
      .then((data) => {
        const map = new Map<string, boolean>()
        data.forEach((p) => map.set(`${p.channel}:${p.event_type}`, p.enabled))
        setPrefs(data)
        setUpdated(map)
      })
      .finally(() => setLoading(false))
  }, [session?.user?.access_token])

  const toggle = async (channel: string, eventType: string) => {
    const current = updated.get(`${channel}:${eventType}`) ?? true
    const next = !current
    const map = new Map(updated)
    map.set(`${channel}:${eventType}`, next)
    setUpdated(map)

    try {
      const existing = prefs.find(
        (p) => p.channel === channel && p.event_type === eventType
      )
      if (existing) {
        const apiFetch = createClientFetch(session?.user?.access_token)
        await apiFetch(`/notifications/prefs/${existing.id}`, {
          method: 'PUT',
          body: JSON.stringify({ channel, event_type: eventType, enabled: next }),
        })
      }
    } catch {
      map.set(`${channel}:${eventType}`, current)
      setUpdated(map)
    }
  }

  if (loading) return <div className="text-muted-foreground">Loading...</div>

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b">
            <th className="text-left px-4 py-2 font-medium">Event</th>
            {CHANNELS.map((ch) => (
              <th key={ch} className="text-center px-4 py-2 font-medium capitalize">
                {ch}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {EVENT_TYPES.map((eventType) => (
            <tr key={eventType} className="border-b hover:bg-muted/50">
              <td className="px-4 py-2 font-medium">{eventType}</td>
              {CHANNELS.map((channel) => {
                const enabled = updated.get(`${channel}:${eventType}`) ?? true
                return (
                  <td key={`${channel}:${eventType}`} className="text-center px-4 py-2">
                    <button
                      onClick={() => toggle(channel, eventType)}
                      className={`relative inline-flex h-6 w-11 items-center rounded-full transition-colors ${
 enabled ? 'bg-primary' : 'bg-border-strong'
 }`}
                    >
                      <span
                        className={`inline-block h-4 w-4 transform rounded-full bg-card transition-transform ${
 enabled ? 'translate-x-6' : 'translate-x-1'
 }`}
                      />
                    </button>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
      {prefs.length === 0 && (
        <div className="text-center py-8 text-muted-foreground">
          No notification preferences configured. Toggle any channel to enable.
        </div>
      )}
    </div>
  )
}
