/**
 * Unit tests for lib/features.ts.
 *
 * Tests focus on the pure helper functions (keyToEnvVar, getEnvOverride) and the
 * isEnabled / getAllFeatures functions with a mocked API. These run in Node without
 * a browser or Next.js runtime.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Re-import after each env mutation to get fresh module state.
async function importFeatures() {
  vi.resetModules()
  return import('@/lib/features')
}

describe('keyToEnvVar', () => {
  it('maps simple keys to FEATURE_<KEY_UPPER>', async () => {
    const { keyToEnvVar } = await importFeatures()
    expect(keyToEnvVar('chat')).toBe('FEATURE_CHAT')
    expect(keyToEnvVar('exports')).toBe('FEATURE_EXPORTS')
    expect(keyToEnvVar('lineage')).toBe('FEATURE_LINEAGE')
  })

  it('replaces dots with underscores for dotted keys', async () => {
    const { keyToEnvVar } = await importFeatures()
    expect(keyToEnvVar('embed.powerbi')).toBe('FEATURE_EMBED_POWERBI')
    expect(keyToEnvVar('embed.tableau')).toBe('FEATURE_EMBED_TABLEAU')
    expect(keyToEnvVar('embed.custom_react')).toBe('FEATURE_EMBED_CUSTOM_REACT')
    expect(keyToEnvVar('embed.streamlit')).toBe('FEATURE_EMBED_STREAMLIT')
  })
})

describe('getEnvOverride', () => {
  beforeEach(() => {
    // Clean known FEATURE_* vars before each test
    for (const key of ['FEATURE_CHAT', 'FEATURE_EXPORTS', 'FEATURE_EMBED_POWERBI']) {
      delete process.env[key]
    }
  })

  it('returns null when env var is not set', async () => {
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('chat')).toBeNull()
  })

  it('returns null when env var is empty string', async () => {
    process.env.FEATURE_CHAT = ''
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('chat')).toBeNull()
  })

  it('returns true for "true"', async () => {
    process.env.FEATURE_CHAT = 'true'
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('chat')).toBe(true)
  })

  it('returns true for "1"', async () => {
    process.env.FEATURE_EXPORTS = '1'
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('exports')).toBe(true)
  })

  it('returns true for "yes"', async () => {
    process.env.FEATURE_CHAT = 'yes'
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('chat')).toBe(true)
  })

  it('returns false for "false"', async () => {
    process.env.FEATURE_CHAT = 'false'
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('chat')).toBe(false)
  })

  it('returns false for "0"', async () => {
    process.env.FEATURE_EXPORTS = '0'
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('exports')).toBe(false)
  })

  it('handles dotted keys via env var lookup', async () => {
    process.env.FEATURE_EMBED_POWERBI = 'false'
    const { getEnvOverride } = await importFeatures()
    expect(getEnvOverride('embed.powerbi')).toBe(false)
  })
})

describe('isEnabled', () => {
  beforeEach(() => {
    vi.resetModules()
    delete process.env.FEATURE_CHAT
    delete process.env.FEATURE_LINEAGE
  })

  it('returns env override when set — no API call needed', async () => {
    process.env.FEATURE_CHAT = 'true'
    const { isEnabled } = await importFeatures()
    const result = await isEnabled('chat')
    expect(result).toBe(true)

    // apiFetch must NOT have been called since env var short-circuits
    const { apiFetch } = await import('@/lib/api')
    expect(apiFetch).not.toHaveBeenCalled()
  })

  it('returns false env override even when API would return true', async () => {
    process.env.FEATURE_CHAT = 'false'
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue([{ feature_key: 'chat', enabled: true, env_override: false }])

    const { isEnabled } = await importFeatures()
    expect(await isEnabled('chat')).toBe(false)
  })

  it('returns API value when no env override is set', async () => {
    delete process.env.FEATURE_LINEAGE
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue([
      { feature_key: 'lineage', enabled: true, env_override: false },
    ])

    const { isEnabled } = await importFeatures()
    expect(await isEnabled('lineage')).toBe(true)
  })

  it('returns false for unknown key not in API response', async () => {
    delete process.env.FEATURE_GOVERNANCE
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue([])

    const { isEnabled } = await importFeatures()
    expect(await isEnabled('governance')).toBe(false)
  })

  it('returns false when API throws', async () => {
    delete process.env.FEATURE_RETENTION
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockRejectedValue(new Error('network error'))

    const { isEnabled } = await importFeatures()
    expect(await isEnabled('retention')).toBe(false)
  })
})

describe('getAllFeatures', () => {
  beforeEach(() => {
    vi.resetModules()
    for (const k of Object.keys(process.env)) {
      if (k.startsWith('FEATURE_')) delete process.env[k]
    }
  })

  it('merges API values with env overrides', async () => {
    process.env.FEATURE_CHAT = 'false'  // override: disable chat
    const { apiFetch } = await import('@/lib/api')
    vi.mocked(apiFetch).mockResolvedValue([
      { feature_key: 'chat', enabled: true, env_override: false },
      { feature_key: 'exports', enabled: true, env_override: false },
    ])

    const { getAllFeatures } = await importFeatures()
    const features = await getAllFeatures()

    expect(features['chat']).toBe(false)   // env wins
    expect(features['exports']).toBe(true) // API value kept
  })
})
