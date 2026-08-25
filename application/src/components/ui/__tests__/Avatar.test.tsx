// @vitest-environment jsdom
/**
 * Tests for the shared user avatar.
 *
 * The initials fallback is what most users will actually see, and its colour has
 * to be stable — an avatar that changes colour between renders is worse than no
 * avatar, because recognition is the only job it has without an image.
 */
import '@testing-library/jest-dom/vitest'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { Avatar, AvatarGroup, avatarSrc, userInitials } from '@/components/ui'

describe('userInitials', () => {
  it('takes the first letter of the first two words', () => {
    expect(userInitials('Ada Lovelace', 'ada@example.com')).toBe('AL')
  })

  it('uses two letters of a single-word name', () => {
    expect(userInitials('Ada', 'ada@example.com')).toBe('AD')
  })

  it('falls back to the email local part when there is no name', () => {
    expect(userInitials(null, 'grace@example.com')).toBe('GR')
  })

  it('ignores the domain, which is the same for the whole org', () => {
    expect(userInitials(null, 'ab@verylongcompanyname.com')).toBe('AB')
  })

  it('ignores repeated whitespace in a name', () => {
    expect(userInitials('  Ada   Lovelace ', null)).toBe('AL')
  })

  it('returns a placeholder when there is nothing to work with', () => {
    expect(userInitials(null, null)).toBe('?')
  })
})

describe('avatarSrc', () => {
  it('returns null when there is no avatar', () => {
    expect(avatarSrc(null)).toBeNull()
  })

  it('prefixes an app-relative path with the API origin', () => {
    expect(avatarSrc('/users/1/avatar/a.png')).toMatch(/^https?:\/\/.+\/users\/1\/avatar\/a\.png$/)
  })

  it('leaves an absolute URL alone', () => {
    expect(avatarSrc('https://cdn.test/a.png')).toBe('https://cdn.test/a.png')
  })
})

describe('Avatar', () => {
  it('renders the image when one is set', () => {
    render(<Avatar name="Ada" email="ada@example.com" avatarUrl="/users/1/avatar/a.png" />)

    expect(screen.getByRole('img')).toHaveAttribute('alt', 'Ada')
  })

  it('renders initials when there is no image', () => {
    render(<Avatar name="Ada Lovelace" email="ada@example.com" />)

    expect(screen.getByText('AL')).toBeInTheDocument()
  })

  it('labels the initials fallback with the person, not the letters', () => {
    render(<Avatar name="Ada Lovelace" email="ada@example.com" />)

    expect(screen.getByRole('img', { name: 'Ada Lovelace' })).toBeInTheDocument()
  })

  it('falls back to the email as a label when unnamed', () => {
    render(<Avatar email="ada@example.com" />)

    expect(screen.getByRole('img', { name: 'ada@example.com' })).toBeInTheDocument()
  })

  it('gives the same person the same colour every render', () => {
    const first = render(<Avatar name="Ada" email="ada@example.com" />)
    const firstClass = first.getByRole('img').className
    first.unmount()

    render(<Avatar name="Ada" email="ada@example.com" />)

    expect(screen.getByRole('img').className).toBe(firstClass)
  })

  it('keeps the colour when the display name changes but the identity does not', () => {
    const first = render(<Avatar name="Ada" email="ada@example.com" />)
    const firstClass = first.getByRole('img').className
    first.unmount()

    render(<Avatar name="Ada Lovelace" email="ada@example.com" />)

    expect(screen.getByRole('img').className).toBe(firstClass)
  })

  it('applies the requested size', () => {
    render(<Avatar name="Ada" email="ada@example.com" size="xl" />)

    expect(screen.getByRole('img').className).toContain('h-24')
  })
})

describe('AvatarGroup', () => {
  const people = Array.from({ length: 6 }, (_, i) => ({
    display_name: `Person ${i}`,
    email: `p${i}@example.com`,
    avatar_url: null,
  }))

  it('shows every member when under the limit', () => {
    render(<AvatarGroup users={people.slice(0, 3)} />)

    expect(screen.getAllByRole('img')).toHaveLength(3)
  })

  it('caps the stack and reports the overflow', () => {
    render(<AvatarGroup users={people} max={4} />)

    expect(screen.getAllByRole('img')).toHaveLength(4)
    expect(screen.getByText('+2')).toBeInTheDocument()
  })

  it('shows no overflow chip at exactly the limit', () => {
    render(<AvatarGroup users={people.slice(0, 4)} max={4} />)

    expect(screen.queryByText(/^\+/)).not.toBeInTheDocument()
  })

  it('renders nothing for an empty team', () => {
    render(<AvatarGroup users={[]} />)

    expect(screen.queryAllByRole('img')).toHaveLength(0)
  })
})
