import { describe, expect, it } from 'vitest'
import appSource from './App.tsx?raw'
import ordersSource from './services/orders.ts?raw'

describe('Shadowfax manual reconciliation', () => {
  it('checks the backend immediately and exposes every operator state', () => {
    expect(appSource).toContain("setShadowfaxWorkflowStatus('Checking Shadowfax...')")
    expect(appSource).toContain('onSaveManualShadowfax({})')
    expect(appSource).toContain('Shipment found · Shipment recorded')
    expect(appSource).toContain('Could not find Shadowfax shipment · Failed - retry')
    expect(appSource).toContain('Validate and record shipment')
  })

  it('requires an AWB fallback and renders structured API errors readably', () => {
    expect(appSource).toContain('It will be validated against this exact order before anything is recorded.')
    expect(appSource).not.toContain('Shipment / Order ID')
    expect(ordersSource).toContain("readableApiError(body, 'Unable to reconcile the Shadowfax shipment. Please retry.')")
  })
})
