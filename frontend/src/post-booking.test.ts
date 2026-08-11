import { describe, expect, it } from 'vitest'
import type { Order, OrderCounts } from './services/orders'
import { applyConfirmedBookingState } from './utils/postBooking'
import appSource from './App.tsx?raw'

const order = { internalId: 'order-1', orderNumber: '324700' } as Order
const counts = {
  operations: 10, fresh: 6, previous: 4, follow_up: 3, on_hold: 1,
  labels_to_print: 2, awaiting_confirmation: 0, printed_today: 0, new_orders: 6,
} as OrderCounts
const labels = { labels_to_print: [], awaiting_confirmation: [], printed_today: [] }
const booked = { order_id: 'order-1', provider: 'delhivery', awb: 'AWB-1', booking_status: 'booked', label_print_status: 'not_printed' } as NonNullable<Order['shipment']>

describe('confirmed post-booking queue transition', () => {
  it('removes a confirmed booking from Fresh, updates counts and queues its label', () => {
    const result = applyConfirmedBookingState([order], counts, labels, order.internalId, booked, 'fresh', 'follow_up')
    expect(result.orders).toEqual([])
    expect(result.counts).toMatchObject({ operations: 9, fresh: 5, new_orders: 5, labels_to_print: 3 })
    expect(result.labels.labels_to_print).toEqual([booked])
    expect(result.moved).toBe(true)
  })

  it('removes a confirmed booking from the active Previous Pending view', () => {
    const result = applyConfirmedBookingState([order], counts, labels, order.internalId, booked, 'previous', 'on_hold')
    expect(result.orders).toEqual([])
    expect(result.counts).toMatchObject({ operations: 9, previous: 3, on_hold: 0, labels_to_print: 3 })
  })

  it('does not move an order after a failed or incomplete booking response', () => {
    const incomplete = { ...booked, awb: null, booking_status: 'booking_failed' } as NonNullable<Order['shipment']>
    const result = applyConfirmedBookingState([order], counts, labels, order.internalId, incomplete, 'fresh', 'follow_up')
    expect(result).toMatchObject({ orders: [order], counts, labels, moved: false })
  })

  it('does not duplicate an already queued label', () => {
    const existing = { ...labels, labels_to_print: [booked] }
    const result = applyConfirmedBookingState([order], counts, existing, order.internalId, booked, 'fresh', 'follow_up')
    expect(result.labels.labels_to_print).toHaveLength(1)
    expect(result.counts.labels_to_print).toBe(2)
  })

  it('keeps the open drawer snapshot updated without a full Orders reload', () => {
    const flow = appSource.slice(appSource.indexOf('const applyConfirmedBooking ='), appSource.indexOf('useEffect(() => {', appSource.indexOf('const applyConfirmedBooking =')))
    expect(flow).toContain('applyCanonicalShipment(orderId, shipment)')
    expect(flow).not.toContain('loadOrders')
  })
})
