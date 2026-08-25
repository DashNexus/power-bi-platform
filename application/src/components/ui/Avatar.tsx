/**
 * User avatar: an uploaded image, or initials on a colour derived from identity.
 *
 * Three copies of "initials in a circle" existed before this — in `TopBar`, in
 * `PortalNav`, and inline on the client card — all with different sizes and none
 * able to show an uploaded image. Everything that renders a person now goes
 * through here, so adding a presence dot or a tooltip happens in one place.
 *
 * The fallback colour is hashed from the user's email (or name), so the same
 * person is the same colour on every screen and in every session. A random or
 * index-based colour would reshuffle whenever a list reordered, which makes the
 * avatar useless for recognition — the only job it has when there is no image.
 */
import Image from 'next/image'
import { cn } from '@/lib/utils'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

export type AvatarSize = 'xs' | 'sm' | 'md' | 'lg' | 'xl'

/** Pixel size per step — also the width/height passed to next/image. */
const PIXELS: Record<AvatarSize, number> = { xs: 20, sm: 24, md: 32, lg: 40, xl: 96 }

const SIZE_CLASSES: Record<AvatarSize, string> = {
  xs: 'h-5 w-5 text-[10px]',
  sm: 'h-6 w-6 text-[10px]',
  md: 'h-8 w-8 text-xs',
  lg: 'h-10 w-10 text-sm',
  xl: 'h-24 w-24 text-2xl',
}

/**
 * Fallback tones. Semantic token pairs rather than raw hexes, so each stays
 * legible in both themes — a fixed hex would fail one of them.
 */
const TONES = [
  'bg-primary/15 text-primary',
  'bg-success-subtle text-success-strong',
  'bg-warning-subtle text-warning-strong',
  'bg-info-subtle text-info-strong',
  'bg-accent text-accent-foreground',
  'bg-destructive-subtle text-destructive-strong',
] as const

/** Stable index into TONES for an identity string. */
function toneFor(seed: string): string {
  let hash = 0
  for (let i = 0; i < seed.length; i += 1) hash = (hash * 31 + seed.charCodeAt(i)) | 0
  return TONES[Math.abs(hash) % TONES.length]
}

/**
 * Up to two initials for a person.
 *
 * Falls back through name → email local part → "?", because a user invited but
 * never signed in has an email and nothing else.
 */
export function userInitials(name?: string | null, email?: string | null): string {
  const words = (name ?? '').trim().split(/\s+/).filter(Boolean)
  if (words.length >= 2) return (words[0][0] + words[1][0]).toUpperCase()
  if (words.length === 1) return words[0].slice(0, 2).toUpperCase()

  const local = (email ?? '').split('@')[0]
  if (local) return local.slice(0, 2).toUpperCase()
  return '?'
}

/** Resolve a stored avatar path against the API origin. */
export function avatarSrc(avatarUrl?: string | null): string | null {
  if (!avatarUrl) return null
  return avatarUrl.startsWith('/') ? `${API_BASE}${avatarUrl}` : avatarUrl
}

export interface AvatarProps {
  name?: string | null
  email?: string | null
  avatarUrl?: string | null
  size?: AvatarSize
  /** Ring in the surface colour — for overlapping stacks. */
  ringed?: boolean
  className?: string
}

export function Avatar({
  name,
  email,
  avatarUrl,
  size = 'md',
  ringed,
  className,
}: AvatarProps) {
  const src = avatarSrc(avatarUrl)
  const label = name || email || 'Unknown user'
  const shell = cn(
    'relative shrink-0 overflow-hidden rounded-full select-none',
    SIZE_CLASSES[size],
    ringed && 'ring-2 ring-card',
    className,
  )

  if (src) {
    return (
      <Image
        src={src}
        alt={label}
        title={label}
        width={PIXELS[size]}
        height={PIXELS[size]}
        // Avatars are served from the API origin, which is not in next.config's
        // image domains and would 400 through the optimiser.
        unoptimized
        className={cn(shell, 'object-cover')}
      />
    )
  }

  return (
    <div
      className={cn(shell, 'flex items-center justify-center font-semibold', toneFor(email || label))}
      title={label}
      // The initials are decoration; the name is what a screen reader should get.
      role="img"
      aria-label={label}
    >
      <span aria-hidden>{userInitials(name, email)}</span>
    </div>
  )
}

export interface AvatarGroupProps {
  users: Array<{ display_name?: string | null; email?: string | null; avatar_url?: string | null }>
  size?: AvatarSize
  /** Show at most this many, then a "+N" chip. */
  max?: number
  className?: string
}

/** Overlapping stack of avatars, with a +N overflow chip. */
export function AvatarGroup({ users, size = 'sm', max = 4, className }: AvatarGroupProps) {
  const shown = users.slice(0, max)
  const overflow = users.length - shown.length

  return (
    <div className={cn('flex items-center -space-x-1.5', className)}>
      {shown.map((user, index) => (
        <Avatar
          key={user.email ?? index}
          name={user.display_name}
          email={user.email}
          avatarUrl={user.avatar_url}
          size={size}
          ringed
        />
      ))}
      {overflow > 0 && (
        <span
          className={cn(
            'flex items-center justify-center rounded-full bg-muted font-semibold text-muted-foreground ring-2 ring-card',
            SIZE_CLASSES[size],
          )}
          title={`${overflow} more`}
        >
          +{overflow}
        </span>
      )}
    </div>
  )
}
