import type { Order, OrderCounts } from '../services/orders'

export type LabelQueueState = {
  ready_to_ship: NonNullable<Order['shipment']>[]
  manifested: NonNullable<Order['shipment']>[]
}

export const isConfirmedLabelBooking = (shipment: Order['shipment']): shipment is NonNullable<Order['shipment']> =>
  Boolean(shipment?.awb && shipment.booking_status === 'booked')

export const mergeCanonicalShipment = (order: Order, shipment: Order['shipment']): Order => {
  if (!shipment) return order
  const operationalStatus = isConfirmedLabelBooking(shipment) && !['Shipped', 'Delivered', 'Cancelled'].includes(order.operationalStatus || '')
    ? 'Booked'
    : order.operationalStatus
  return { ...order, shipment, operationalStatus }
}

export function applyConfirmedBookingState(
  orders: Order[], counts: OrderCounts, labels: LabelQueueState,
  orderId: string, shipment: Order['shipment'], queue: string, pendingView: 'follow_up' | 'on_hold',
) {
  if (!isConfirmedLabelBooking(shipment)) return { orders, counts, labels, moved: false }
  const wasDisplayed = orders.some(order => order.internalId === orderId)
  const alreadyQueued = labels.ready_to_ship.some(value => value.order_id === orderId)
  const decrement = (value: number) => Math.max(0, value - (wasDisplayed ? 1 : 0))
  const nextCounts = { ...counts, ready_to_ship: counts.ready_to_ship + (alreadyQueued ? 0 : 1) }
  if (queue === 'fresh') {
    nextCounts.fresh = decrement(counts.fresh)
    nextCounts.new_orders = decrement(counts.new_orders)
    nextCounts.operations = decrement(counts.operations)
  } else if (queue === 'previous') {
    nextCounts.previous = decrement(counts.previous)
    nextCounts.operations = decrement(counts.operations)
    if (pendingView === 'on_hold') nextCounts.on_hold = decrement(counts.on_hold)
    else nextCounts.follow_up = decrement(counts.follow_up)
  }
  return {
    orders: orders.filter(order => order.internalId !== orderId),
    counts: nextCounts,
    labels: alreadyQueued ? labels : { ...labels, ready_to_ship: [{...shipment,dispatch_status:'ready_to_ship' as const}, ...labels.ready_to_ship] },
    moved: true,
  }
}
