import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { OrderStatusBadge } from './components/OrderStatusBadge'
import type { Order } from './services/orders'
import { isBooked, listStatus } from './utils/orderStatus'

const order = (operationalStatus: string | null, shipment: Order['shipment'] = null) => ({
  operationalStatus,
  shipment,
  cancelledAt: null,
  shopifyStatus: null,
  fulfillmentStatus: null,
  payment: 'COD',
  tags: [],
  externalTracking: null,
  addressVerified: false,
  latestCallResult: null,
} as unknown as Order)

describe('order status rendering', () => {
  it('renders different authoritative operational statuses per order', () => {
    const html = renderToStaticMarkup(<div>
      <OrderStatusBadge order={order('Call Pending', { shiprocket_order_id: '1478516896' } as Order['shipment'])} />
      <OrderStatusBadge order={order('Booked', { awb: 'AWB1' } as Order['shipment'])} />
      <OrderStatusBadge order={order('Cancelled')} />
      <OrderStatusBadge order={order('Delivered')} />
    </div>)
    expect(html).toContain('Call Pending')
    expect(html).toContain('Booked')
    expect(html).toContain('Cancelled')
    expect(html).toContain('Delivered')
  })

  it('does not treat placeholder or failed provider rows as booked', () => {
    expect(isBooked(order('Ready for Booking', { shiprocket_order_id: '1478516896', booking_status: 'new' } as Order['shipment']))).toBe(false)
    expect(isBooked(order('Ready for Booking', { provider_order_id: '323693', booking_status: 'failed' } as Order['shipment']))).toBe(false)
    expect(isBooked(order('Booked', { awb: 'AWB1' } as Order['shipment']))).toBe(true)
    expect(isBooked(order('Booked', { provider_order_id: 'P1', booking_status: 'booked' } as Order['shipment']))).toBe(true)
  })

  it('does not show COD confirmed orders as ready before address verification', () => {
    expect(listStatus({ ...order(null), operationalStatus: null, latestCallResult: 'Confirmed', addressVerified: false } as Order)).toBe('Address Verification Pending')
    expect(listStatus({ ...order(null), operationalStatus: null, latestCallResult: 'Confirmed', addressVerified: true } as Order)).toBe('Ready for Booking')
  })

  it('does not retain Address Verification Pending for a canonically verified prepaid order', () => {
    const verifiedPrepaid = { ...order('Address Verification Pending'), operationalStatus: null, payment: 'Prepaid', addressVerified: true } as Order
    expect(listStatus(verifiedPrepaid)).toBe('Ready for Booking')
  })
})
