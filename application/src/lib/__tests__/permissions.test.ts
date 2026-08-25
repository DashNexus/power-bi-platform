import { describe, it, expect } from 'vitest'
import { hasRole, hasAnyRole } from '@/lib/permissions'

describe('hasRole', () => {
  it('returns false when userRole is undefined', () => {
    expect(hasRole(undefined, 'viewer')).toBe(false)
  })

  it('returns true when user has the exact required role', () => {
    expect(hasRole('viewer', 'viewer')).toBe(true)
    expect(hasRole('analyst', 'analyst')).toBe(true)
    expect(hasRole('admin', 'admin')).toBe(true)
    expect(hasRole('superadmin', 'superadmin')).toBe(true)
  })

  it('returns true when user has a higher role than required', () => {
    expect(hasRole('superadmin', 'admin')).toBe(true)
    expect(hasRole('superadmin', 'analyst')).toBe(true)
    expect(hasRole('superadmin', 'viewer')).toBe(true)
    expect(hasRole('admin', 'analyst')).toBe(true)
    expect(hasRole('admin', 'viewer')).toBe(true)
    expect(hasRole('analyst', 'viewer')).toBe(true)
  })

  it('returns false when user has a lower role than required', () => {
    expect(hasRole('viewer', 'analyst')).toBe(false)
    expect(hasRole('viewer', 'admin')).toBe(false)
    expect(hasRole('viewer', 'superadmin')).toBe(false)
    expect(hasRole('analyst', 'admin')).toBe(false)
    expect(hasRole('analyst', 'superadmin')).toBe(false)
    expect(hasRole('admin', 'superadmin')).toBe(false)
  })

  it('returns false for unknown role strings', () => {
    expect(hasRole('editor', 'viewer')).toBe(false)
    expect(hasRole('guest', 'viewer')).toBe(false)
  })
})

describe('hasAnyRole', () => {
  it('returns true when user role satisfies any of the specified minimums', () => {
    expect(hasAnyRole('admin', 'analyst', 'admin')).toBe(true)
    expect(hasAnyRole('analyst', 'analyst', 'admin')).toBe(true)
  })

  it('returns false when user role does not satisfy any required role', () => {
    expect(hasAnyRole('viewer', 'analyst', 'admin')).toBe(false)
    expect(hasAnyRole('analyst', 'admin', 'superadmin')).toBe(false)
  })

  it('returns false when userRole is undefined', () => {
    expect(hasAnyRole(undefined, 'viewer')).toBe(false)
    expect(hasAnyRole(undefined, 'analyst', 'admin')).toBe(false)
  })

  it('superadmin satisfies any role check', () => {
    expect(hasAnyRole('superadmin', 'superadmin')).toBe(true)
    expect(hasAnyRole('superadmin', 'admin')).toBe(true)
    expect(hasAnyRole('superadmin', 'viewer')).toBe(true)
  })
})
