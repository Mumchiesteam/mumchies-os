import type { Order, OrderCounts } from '../services/orders'

export type LabelQueueState = {
  labels_to_print: NonNullable<Order['shipment']>[]
  awaiting_confirmation: NonNullable<Order['shipment']>[]
  printed_today: NonNullable<Order['shipment']>[]
}

export const isConfirmedLabelBooking = (shipment: Order['shipment']): shipment is NonNullable<Order['shipment']> =>
  Boolean(shipment?.awb && shipment.booking_status === 'booked')

export function applyConfirmedBookingState(
  orders: Order[], counts: OrderCounts, labels: LabelQueueState,
  orderId: string, shipment: Order['shipment'], queue: string, pendingView: 'follow_up' | 'on_hold',
) {
  if (!isConfirmedLabelBooking(shipment)) return { orders, counts, labels, moved: false }
  const wasDisplayed = orders.some(order => order.internalId === orderId)
  const alreadyQueued = labels.labels_to_print.some(value => value.order_id === orderId)
  const decrement = (value: number) => Math.max(0, value - (wasDisplayed ? 1 : 0))
  const nextCounts = { ...counts, labels_to_print: counts.labels_to_print + (alreadyQueued ? 0 : 1) }
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
    labels: alreadyQueued ? labels : { ...labels, labels_to_print: [shipment, ...labels.labels_to_print] },
    moved: true,
  }
}
