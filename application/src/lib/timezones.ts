/**
 * IANA time zone names for the profile picker.
 *
 * Read from the browser when it supports `Intl.supportedValuesOf`, which every
 * current engine does — that keeps the list correct as the tz database changes
 * rather than freezing whatever was true the day this shipped. The literal
 * fallback exists for older engines and for the jsdom test environment.
 */

const FALLBACK_TIMEZONES = [
  'UTC',
  'America/New_York',
  'America/Chicago',
  'America/Denver',
  'America/Los_Angeles',
  'America/Anchorage',
  'America/Toronto',
  'America/Vancouver',
  'America/Mexico_City',
  'America/Bogota',
  'America/Sao_Paulo',
  'Europe/London',
  'Europe/Dublin',
  'Europe/Lisbon',
  'Europe/Madrid',
  'Europe/Paris',
  'Europe/Berlin',
  'Europe/Amsterdam',
  'Europe/Zurich',
  'Europe/Stockholm',
  'Europe/Warsaw',
  'Europe/Athens',
  'Europe/Istanbul',
  'Europe/Moscow',
  'Africa/Lagos',
  'Africa/Johannesburg',
  'Africa/Nairobi',
  'Africa/Cairo',
  'Asia/Jerusalem',
  'Asia/Dubai',
  'Asia/Karachi',
  'Asia/Kolkata',
  'Asia/Dhaka',
  'Asia/Bangkok',
  'Asia/Singapore',
  'Asia/Hong_Kong',
  'Asia/Shanghai',
  'Asia/Tokyo',
  'Asia/Seoul',
  'Australia/Perth',
  'Australia/Brisbane',
  'Australia/Sydney',
  'Pacific/Auckland',
]

function loadTimezones(): string[] {
  const supported = (
    Intl as typeof Intl & { supportedValuesOf?: (key: string) => string[] }
  ).supportedValuesOf

  if (typeof supported === 'function') {
    try {
      const zones = supported('timeZone')
      if (zones.length > 0) return zones
    } catch {
      // Fall through — an engine that throws here is one that cannot enumerate.
    }
  }
  return FALLBACK_TIMEZONES
}

export const TIMEZONES: string[] = loadTimezones()

/** The viewer's own zone, for defaulting a picker. */
export function detectTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null
  } catch {
    return null
  }
}
