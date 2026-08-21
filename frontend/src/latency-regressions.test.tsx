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

  it('clears stale frontend selection whenever lookup clears backend persistence', () => {
    const flow = source.slice(source.indexOf('const checkCouriers'), source.indexOf('const selectCourier'))
    expect(flow).toContain('setSelectedCourierId(null)')
    expect(flow).toContain('selected_courier: null')
    expect(flow).not.toContain('!sorted.some')
  })

  it('keeps one lookup in flight, clears loading, and rejects stale drawer responses', () => {
    const flow = source.slice(source.indexOf('const checkCouriers'), source.indexOf('const selectCourier'))
    expect(flow).toContain('if (courierRequestOrderRef.current === orderId) return')
    expect(flow).toContain('if (generation !== drawerGenerationRef.current) return')
    expect(flow).toContain('courierRequestOrderRef.current = null')
    expect(flow).toContain('setCourierLoading(false)')
    expect(flow).toContain("result.lookup_status === 'manual_only'")
  })

  it('does not wait for eligibility after persisting a courier selection', () => {
    const flow = source.slice(source.indexOf('const selectCourier'), source.indexOf('const bookShipment'))
    expect(flow).not.toContain('refreshEligibility(')
    expect(flow).toContain('courierSelectionMatches')
  })

  it('keeps Book Shipment disabled without a matching persisted selection', () => {
    expect(source).toContain('const selectedCourierPersisted = courierSelectionMatches')
    const guard = source.slice(source.indexOf('const canBookShipment'), source.indexOf('const requirementLabels'))
    expect(guard).toContain('selectedCourierPersisted')
  })

  it('shows saved address before the secondary eligibility refresh', () => {
    const flow = source.slice(source.indexOf('const saveAndVerifyAddress'), source.indexOf('const checkCouriers'))
    expect(flow).toContain('setNotice(result.verified')
    expect(flow).toContain('void getBookingEligibility(orderId)')
    expect(flow).not.toContain('await getBookingEligibility(orderId)')
  })

  it('shows booked before the secondary canonical readback', () => {
    const flow = source.slice(source.indexOf('const bookShipment'), source.indexOf('const saveManualShadowfax'))
    expect(flow).toContain("setNotice(result.existing ? 'Existing shipment loaded' : 'Shipment booked')")
    expect(flow).toContain('void getOrderOperations(orderId)')
    expect(flow).not.toContain('await getOrderOperations(orderId)')
    expect(flow).not.toContain('loadOrders(')
  })
})
