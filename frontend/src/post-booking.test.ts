import { describe, expect, it } from 'vitest'
import type { Order, OrderCounts } from './services/orders'
import { applyConfirmedBookingState, mergeCanonicalShipment } from './utils/postBooking'
import appSource from './App.tsx?raw'

const order = { internalId: 'order-1', orderNumber: '324700' } as Order
const counts = {
  operations: 10, fresh: 6, previous: 4, follow_up: 3, on_hold: 1,
  ready_to_ship: 2, manifested: 0, new_orders: 6,
} as OrderCounts
const labels = { ready_to_ship: [], manifested: [] }
const booked = { order_id: 'order-1', provider: 'delhivery', awb: 'AWB-1', booking_status: 'booked', label_print_status: 'not_printed' } as NonNullable<Order['shipment']>

describe('confirmed post-booking queue transition', () => {
  it('removes a confirmed booking from Fresh, updates counts and queues its label', () => {
    const result = applyConfirmedBookingState([order], counts, labels, order.internalId, booked, 'fresh', 'follow_up')
    expect(result.orders).toEqual([])
    expect(result.counts).toMatchObject({ operations: 9, fresh: 5, new_orders: 5, ready_to_ship: 3 })
    expect(result.labels.ready_to_ship[0]).toMatchObject({order_id:'order-1',dispatch_status:'ready_to_ship'})
    expect(result.moved).toBe(true)
  })

  it('removes a confirmed booking from the active Previous Pending view', () => {
    const result = applyConfirmedBookingState([order], counts, labels, order.internalId, booked, 'previous', 'on_hold')
    expect(result.orders).toEqual([])
    expect(result.counts).toMatchObject({ operations: 9, previous: 3, on_hold: 0, ready_to_ship: 3 })
  })

  it('does not move an order after a failed or incomplete booking response', () => {
    const incomplete = { ...booked, awb: null, booking_status: 'booking_failed' } as NonNullable<Order['shipment']>
    const result = applyConfirmedBookingState([order], counts, labels, order.internalId, incomplete, 'fresh', 'follow_up')
    expect(result).toMatchObject({ orders: [order], counts, labels, moved: false })
  })

  it('does not duplicate an already queued label', () => {
    const existing = { ...labels, ready_to_ship: [booked] }
    const result = applyConfirmedBookingState([order], counts, existing, order.internalId, booked, 'fresh', 'follow_up')
    expect(result.labels.ready_to_ship).toHaveLength(1)
    expect(result.counts.ready_to_ship).toBe(2)
  })

  it('keeps the open drawer snapshot updated without a full Orders reload', () => {
    const flow = appSource.slice(appSource.indexOf('const applyConfirmedBooking ='), appSource.indexOf('useEffect(() => {', appSource.indexOf('const applyConfirmedBooking =')))
    expect(flow).toContain('applyCanonicalShipment(orderId, shipment)')
    expect(flow).not.toContain('loadOrders')
  })

  it('immediately promotes the open drawer to Booked while preserving the AWB', () => {
    const merged = mergeCanonicalShipment({ ...order, operationalStatus: 'Ready for Booking' }, booked)
    expect(merged.operationalStatus).toBe('Booked')
    expect(merged.shipment?.awb).toBe('AWB-1')
  })

  it('clears stale courier errors after later successful operations', () => {
    expect(appSource).toContain("setCourierError(result.warning ? `Shiprocket cleanup failed: ${result.warning}` : '')")
    expect(appSource).toContain("['cancelled', 'not_applicable', 'resolved'].includes(result.status)")
  })
})
