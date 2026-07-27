import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { OrderStatusBadge } from './components/OrderStatusBadge'
import type { Order } from './services/orders'

const order = (operationalStatus: string, shipment: Order['shipment'] = null) => ({
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
})
