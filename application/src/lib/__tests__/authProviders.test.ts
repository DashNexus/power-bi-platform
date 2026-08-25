/**
 * Tests for SSO provider discovery.
 *
 * This module decides both which Auth.js providers get registered and which
 * buttons the login page renders. A provider that appears in one list but not
 * the other produces a button that dead-ends at an opaque provider error, so the
 * two must stay derived from the same source.
 */
import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest'

const OAUTH_VARS = ['AZURE_AD_CLIENT_ID', 'AZURE_AD_CLIENT_SECRET', 'AZURE_AD_TENANT_ID']

async function importModule() {
  vi.resetModules()
  return import('@/lib/authProviders')
}

describe('getConfiguredProviders', () => {
  beforeEach(() => {
    for (const key of OAUTH_VARS) delete process.env[key]
  })

  afterEach(() => {
    for (const key of OAUTH_VARS) delete process.env[key]
  })

  it('returns nothing when Entra is not configured', async () => {
    const { getConfiguredProviders } = await importModule()

    expect(getConfiguredProviders()).toEqual([])
  })

  it('returns the provider once both its ID and secret are set', async () => {
    process.env.AZURE_AD_CLIENT_ID = 'entra-id'
    process.env.AZURE_AD_CLIENT_SECRET = 'entra-secret'
    const { getConfiguredProviders } = await importModule()

    expect(getConfiguredProviders()).toEqual([
      {
        provider: 'microsoft',
        clientId: 'entra-id',
        clientSecret: 'entra-secret',
        tenantId: undefined,
      },
    ])
  })

  it('skips a provider whose secret is missing rather than half-registering it', async () => {
    process.env.AZURE_AD_CLIENT_ID = 'entra-id'
    const { getConfiguredProviders } = await importModule()

    expect(getConfiguredProviders()).toEqual([])
  })

  it('skips a provider whose value is only whitespace', async () => {
    process.env.AZURE_AD_CLIENT_ID = '  '
    process.env.AZURE_AD_CLIENT_SECRET = 'entra-secret'
    const { getConfiguredProviders } = await importModule()

    expect(getConfiguredProviders()).toEqual([])
  })

  it('carries the Entra tenant ID through when present', async () => {
    process.env.AZURE_AD_CLIENT_ID = 'entra-id'
    process.env.AZURE_AD_CLIENT_SECRET = 'entra-secret'
    process.env.AZURE_AD_TENANT_ID = 'tenant-123'
    const { getConfiguredProviders } = await importModule()

    expect(getConfiguredProviders()[0]).toMatchObject({ tenantId: 'tenant-123' })
  })

  it('leaves the tenant ID undefined so Entra falls back to the common issuer', async () => {
    process.env.AZURE_AD_CLIENT_ID = 'entra-id'
    process.env.AZURE_AD_CLIENT_SECRET = 'entra-secret'
    const { getConfiguredProviders } = await importModule()

    expect(getConfiguredProviders()[0].tenantId).toBeUndefined()
  })
})

describe('getLoginProviders', () => {
  beforeEach(() => {
    for (const key of OAUTH_VARS) delete process.env[key]
  })

  afterEach(() => {
    for (const key of OAUTH_VARS) delete process.env[key]
  })

  it('exposes a label per configured provider and never a secret', async () => {
    process.env.AZURE_AD_CLIENT_ID = 'entra-id'
    process.env.AZURE_AD_CLIENT_SECRET = 'entra-secret'
    const { getLoginProviders } = await importModule()

    const providers = await getLoginProviders()

    expect(providers).toEqual([{ provider: 'microsoft', label: 'Sign in with Microsoft' }])
    expect(JSON.stringify(providers)).not.toContain('entra-secret')
  })

  it('renders no SSO button while Entra is unconfigured', async () => {
    const { getLoginProviders } = await importModule()

    expect(await getLoginProviders()).toEqual([])
  })

  it('lists exactly the providers Auth.js will have registered', async () => {
    process.env.AZURE_AD_CLIENT_ID = 'entra-id'
    process.env.AZURE_AD_CLIENT_SECRET = 'entra-secret'
    const { getConfiguredProviders, getLoginProviders } = await importModule()

    const buttons = (await getLoginProviders()).map(p => p.provider)
    const registered = getConfiguredProviders().map(p => p.provider)

    expect(buttons).toEqual(registered)
  })
})
