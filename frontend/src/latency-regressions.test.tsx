import { describe, expect, it } from 'vitest'
import source from './App.tsx?raw'

describe('Orders latency regressions', () => {
  it('does not make loadOrders depend on drawer identity', () => {
    const dependencyLine = source.match(/\}, \[attemptFilter[^\n]+\]\)/)?.[0] || ''
    expect(dependencyLine).not.toContain('selectedOrderId')
  })

  it('does not wait for full Orders reload before call-save success', () => {
    const flow = source.slice(source.indexOf('const saveCallLog'), source.indexOf('const saveAddressConfirmation'))
    expect(flow).toContain("setNotice('Call attempt saved')")
    expect(flow).not.toContain('await loadOrders()')
    expect(flow).not.toContain('getOrderOperations(')
  })

  it('loads Shiprocket cleanup only from its explicit control', () => {
    expect(source).not.toContain('if (loads.orders) { refreshLabels(); refreshCleanup() }')
    expect(source).toContain("if (tab.key === 'shiprocket_cleanup') { refreshCleanup();")
  })

  it('does not refresh eligibility after courier quotes', () => {
    const flow = source.slice(source.indexOf('const checkCouriers'), source.indexOf('const selectCourier'))
    expect(flow).not.toContain('refreshEligibility(orderId)')
  })
})
