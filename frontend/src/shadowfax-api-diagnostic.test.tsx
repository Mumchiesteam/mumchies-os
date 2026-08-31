import { describe, expect, it } from 'vitest'
import appSource from './App.tsx?raw'
import serviceSource from './services/orders.ts?raw'

describe('Shadowfax API diagnostic', () => {
  it('uses the authenticated read-only health-check endpoint', () => {
    expect(serviceSource).toContain('getShadowfaxHealthCheck')
    expect(serviceSource).toContain('/api/v1/shadowfax/health-check')
    const flow = serviceSource.slice(serviceSource.indexOf('export async function getShadowfaxHealthCheck'), serviceSource.indexOf('export type ShadowfaxShipmentRowDiagnostic'))
    expect(flow).not.toContain("method: 'POST'")
    expect(flow).not.toContain('shadowfax_token')
  })

  it('shows compact operator feedback without exposing credentials', () => {
    expect(appSource).toContain("shadowfaxHealthChecking ? 'Testing...' : 'Test Shadowfax API'")
    for (const label of ['Overall:', 'Auth:', 'Serviceability:', 'Client Mapping:', 'Create Order API:', 'Status:']) {
      expect(appSource).toContain(label)
    }
    expect(appSource).not.toContain('SHADOWFAX_TOKEN')
  })
})
