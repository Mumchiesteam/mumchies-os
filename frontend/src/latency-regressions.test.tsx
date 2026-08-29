import { describe, expect, it } from 'vitest'
import source from './App.tsx?raw'

describe('Orders latency regressions', () => {
  it('does not make loadOrders depend on drawer identity', () => {
    const dependencyLine = source.match(/\}, \[attemptFilter[^\n]+\]\)/)?.[0] || ''
    expect(dependencyLine).not.toContain('selectedOrderId')
  })

  it('loads drawer reads in parallel and aborts the prior order on switch', () => {
    const parallelRead = source.indexOf('const [ops, eligibility]')
    const flow = source.slice(source.lastIndexOf('useEffect', parallelRead), source.indexOf('const openOrder', parallelRead))
    expect(flow).toContain('const controller = new AbortController()')
    expect(flow).toContain('await Promise.all([')
    expect(flow).toContain('getOrderOperations(orderId, controller.signal)')
    expect(flow).toContain('getBookingEligibility(orderId, controller.signal)')
    expect(flow).toContain('return () => controller.abort()')
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

  it('keeps persisted selection during a same-context read-only refresh and clears it only for changed context', () => {
    const flow = source.slice(source.indexOf('const checkCouriers'), source.indexOf('const selectCourier'))
    expect(flow).toContain('const contextChanged = previous.contextKey !== null && previous.contextKey !== quoteContext.key')
    expect(flow).toContain('selectedKey: contextChanged ? null : previous.selectedKey')
    expect(flow).not.toContain('selected_courier: null')
  })

  it('binds each lookup response to one courier session and settles the timeout without waiting for fetch rejection', () => {
    const flow = source.slice(source.indexOf('const checkCouriers'), source.indexOf('const selectCourier'))
    expect(flow).toContain("courierRequestRef.current?.controller.abort()")
    expect(flow).toContain('isCurrentCourierSession(current, { orderId, generation, contextKey: quoteContext.key, requestId })')
    expect(flow).toContain('result.client_context_key !== quoteContext.key')
    expect(flow).toContain('const timeout = window.setTimeout')
    expect(flow).toContain('requestId: requestId + 1')
    expect(flow).toContain("phase: hasValidRates ? 'ready' : 'error'")
    expect(flow).toContain('Courier options refresh timed out. Displayed rates are still available.')
    expect(flow).toContain("phase: active.rates.length > 0 ? 'ready' : 'error'")
    expect(flow).toContain("result.lookup_status === 'manual_only'")
    expect(flow).toContain("message === 'Failed to fetch'")
    expect(flow).toContain('Courier lookup request failed before reaching the server.')
  })

  it('does not wait for eligibility after persisting a courier selection', () => {
    const flow = source.slice(source.indexOf('const selectCourier'), source.indexOf('const bookShipment'))
    expect(flow).not.toContain('refreshEligibility(')
    expect(flow).toContain('courierSelectionMatches')
  })

  it('guards COD confirmation eligibility readback by current drawer identity', () => {
    const flow = source.slice(source.indexOf('const saveCallLog'), source.indexOf('const saveAddressConfirmation'))
    expect(flow).toContain('const orderId = selectedOrder.internalId')
    expect(flow).toContain('const generation = drawerGenerationRef.current')
    expect(flow).toContain('if (generation !== drawerGenerationRef.current || selectedOrderId !== orderId) return')
    expect(flow).toContain('if (generation === drawerGenerationRef.current && selectedOrderId === orderId) setBookingEligibility(result)')
    expect(flow).not.toContain('.then(setBookingEligibility)')
  })

  it('keeps courier selection identity composite in drawer state and rendering', () => {
    expect(source).toContain('selectedKey: courierSelectionKey(result.selected_courier)')
    expect(source).toContain('const selectedCourier = courierOptions.find(option => courierSelectionKey(option) === selectedCourierKey)')
    expect(source).toContain('const optionSelectionKey = courierSelectionKey(option)')
    expect(source).toContain('key={optionSelectionKey')
  })

  it('keeps Book Shipment disabled without a matching persisted selection', () => {
    expect(source).toContain('const selectedCourierPersisted = courierSelectionMatches')
    const guard = source.slice(source.indexOf('const canBookShipment'), source.indexOf('const requirementLabels'))
    expect(guard).toContain('selectedCourierPersisted')
  })

  it('still sends one select request from one eligible card click', () => {
    const card = source.slice(source.indexOf('{courierOptions.map(option =>'), source.indexOf("{selectedCourier?.provider === 'shadowfax'"))
    const calls = card.match(/onSelectCourier\(option, currentQuoteContextKey, packageNumbers\)/g) || []
    expect(calls).toHaveLength(1)
    expect(card).toContain('disabled={!quoteGate.enabled || Boolean(selectingCourierKey)}')
  })

  it('shows pending selection feedback without treating it as a persisted courier', () => {
    const flow = source.slice(source.indexOf('const selectCourier'), source.indexOf('const bookShipment'))
    expect(flow).toContain('selectingKey: courierSelectionKey(courier)')
    expect(flow).toContain('selectedKey: courierSelectionKey(result.selected_courier), selectingKey: null')
    expect(flow).toContain('isCurrentCourierSession(current, courierSelectionInFlight.current)')
    const card = source.slice(source.indexOf('{courierOptions.map(option =>'), source.indexOf("{selectedCourier?.provider === 'shadowfax'"))
    expect(card).toContain('Selecting</span>')
    expect(card).toContain('Boolean(selectingCourierKey)')
    expect(source).toContain('Selecting courier')
  })

  it('changes the booking CTA immediately while courier persistence is pending', () => {
    const footer = source.slice(source.indexOf('{selectingCourierKey ?'), source.indexOf('</button>{!canBookShipment'))
    expect(footer).toContain('Selecting courier')
    expect(footer).toContain('Book Shipment')
  })

  it('does not send a duplicate select request while a courier is pending', () => {
    const flow = source.slice(source.indexOf('const selectCourier'), source.indexOf('const bookShipment'))
    expect(flow).toContain('courierSelectionInFlight.current !== null')
    const card = source.slice(source.indexOf('{courierOptions.map(option =>'), source.indexOf("{selectedCourier?.provider === 'shadowfax'"))
    expect(card).toContain('disabled={!quoteGate.enabled || Boolean(selectingCourierKey)}')
  })

  it('restores the unselected UI after a failed courier selection', () => {
    const flow = source.slice(source.indexOf('const selectCourier'), source.indexOf('const bookShipment'))
    expect(flow).toContain('} catch (err) {')
    expect(flow).toContain('selectingKey: null, error: (err as Error).message')
  })

  it('rejects delayed select responses from a previous drawer order', () => {
    const flow = source.slice(source.indexOf('const selectCourier'), source.indexOf('const bookShipment'))
    expect(flow).toContain('const orderId = selectedOrder?.internalId')
    expect(flow).toContain('const generation = drawerGenerationRef.current')
    expect(flow).toContain('isCurrentCourierSession(current, courierSelectionInFlight.current)')
    expect(flow).toContain('courierSelectionInFlight.current.orderId === orderId')
  })

  it('rebinds every courier gate input when moving directly from A to B', () => {
    const open = source.slice(source.indexOf('const openOrder'), source.indexOf('const statusFromOrder'))
    for (const reset of ['courierRequestRef.current?.controller.abort()', 'courierSelectionInFlight.current = null', 'setCourierSession(newCourierSession(orderId, drawerGenerationRef.current))', 'setBookingEligibility(null)', 'setOperations(null)', 'setAddressDraft(emptyAddressDraft())']) {
      expect(open).toContain(reset)
    }
    expect(source).toContain('key={selectedOrder.internalId}')
    const gate = source.slice(source.indexOf('const currentQuoteContextKey'), source.indexOf('const preparingBooking'))
    expect(gate).toContain('orderId: order.internalId')
    expect(gate).toContain('isCurrentCourierSession(courierSession')
    expect(gate).toContain('activeQuoteSession.bookingReadiness.eligible')
  })

  it('does not carry A disabled readiness into an eligible B quote', () => {
    const flow = source.slice(source.indexOf('const checkCouriers'), source.indexOf('const selectCourier'))
    expect(flow).toContain('setCourierSession(next)')
    expect(flow).toContain('bookingReadiness: result.booking_readiness')
    expect(flow).toContain('result.client_context_key !== quoteContext.key')
  })

  it('keeps same-context rates selectable during refresh and returns to ready after refresh failure', () => {
    const flow = source.slice(source.indexOf('const checkCouriers'), source.indexOf('const selectCourier'))
    expect(flow).toContain("phase: retainPriorRates ? 'refreshing' : 'loading'")
    expect(flow).toContain("phase: active.rates.length > 0 ? 'ready' : 'error'")
    const gate = source.slice(source.indexOf('const quoteGate'), source.indexOf('const preparingBooking'))
    expect(gate).toContain("activeQuoteSession?.phase === 'refreshing'")
    const selection = source.slice(source.indexOf('const selectCourier'), source.indexOf('const bookShipment'))
    expect(selection).toContain("session.phase !== 'ready' && session.phase !== 'refreshing'")
  })

  it('does not auto-loop a failed, timed-out, or already-refreshing quote request', () => {
    const effect = source.slice(source.indexOf('if (!canCheckCouriers'), source.indexOf("console.info('courier_prefetch_started'"))
    expect(effect).toContain("courierSession.phase === 'error'")
    expect(effect).toContain("courierSession.phase === 'refreshing'")
    expect(source).toContain('previous.contextKey === quoteContext.key && (previous.phase === \'loading\' || previous.phase === \'refreshing\')')
  })

  it('applies saved address and awaits authoritative eligibility before completing Save & Verify', () => {
    const flow = source.slice(source.indexOf('const saveAndVerifyAddress'), source.indexOf('const checkCouriers'))
    expect(flow).toContain('setNotice(result.verified')
    expect(flow).toContain('await getBookingEligibility(orderId)')
    expect(flow).toContain('setBookingEligibility(freshEligibility)')
  })

  it('does not surface stale Save & Verify completion or error after switching drawer order', () => {
    const flow = source.slice(source.indexOf('const saveAndVerifyAddress'), source.indexOf('const checkCouriers'))
    expect(flow).toContain('if (generation !== drawerGenerationRef.current || selectedOrderId !== orderId) return')
    expect(flow).toContain('if (generation === drawerGenerationRef.current && selectedOrderId === orderId) setBookingEligibility(freshEligibility)')
    expect(flow).toContain('if (generation === drawerGenerationRef.current && selectedOrderId === orderId) {')
    expect(flow).toContain('setNotice((err as Error).message)')
    expect(flow).toContain('return undefined')
  })

  it('does not mark COD confirmation as Ready for Booking until address is verified', () => {
    const flow = source.slice(source.indexOf('const saveCallLog'), source.indexOf('const saveAddressConfirmation'))
    expect(flow).toContain("updated.call_logs?.[0]?.result === 'Confirmed' ? (updated.address_verified ? 'Ready for Booking' : 'Address Verification Pending')")
  })

  it('shows booked before the secondary canonical readback', () => {
    const flow = source.slice(source.indexOf('const bookShipment'), source.indexOf('const saveManualShadowfax'))
    expect(flow).toContain("setNotice(result.existing ? 'Existing shipment loaded' : 'Shipment booked')")
    expect(flow).toContain('void getOrderOperations(orderId)')
    expect(flow).not.toContain('await getOrderOperations(orderId)')
    expect(flow).not.toContain('loadOrders(')
  })
})
