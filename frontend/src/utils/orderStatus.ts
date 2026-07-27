import type { Order } from '../services/orders'

export type OperationalStatus = 'Call Pending' | 'Callback Required' | 'Address Verification Pending' | 'Ready for Booking' | 'Booked' | 'Shipped' | 'NDR' | 'Delivered' | 'Cancelled' | 'Needs Review'

export const isCancelled = (order: Order) => Boolean(order.cancelledAt || order.shopifyStatus === 'cancelled' || (order.payment === 'COD' && order.tags.join(' ').toLowerCase().includes('cancel')))
const isShipped = (order: Order) => {
  const status = `${order.fulfillmentStatus || ''} ${order.shopifyStatus || ''} ${order.tags.join(' ')} ${order.externalTracking?.status || ''}`.toLowerCase()
  return status.includes('fulfilled') || status.includes('partial') || status.includes('shipped') || status.includes('picked up') || status.includes('dispatched') || status.includes('in transit') || status.includes('out for delivery') || Boolean(order.externalTracking?.awb)
}
const isDelivered = (order: Order) => `${order.fulfillmentStatus || ''} ${order.shopifyStatus || ''} ${order.tags.join(' ')} ${order.externalTracking?.status || ''}`.toLowerCase().includes('delivered')
const isNdr = (order: Order) => `${order.tags.join(' ')} ${order.shopifyStatus || ''}`.toLowerCase().includes('ndr')
const isBooked = (order: Order) => Boolean(order.shipment?.awb || order.shipment?.shipment_id)

export const hasShipmentEvidence = (order: Order) => isBooked(order) || isShipped(order) || isDelivered(order) || isNdr(order)

export const listStatus = (order: Order): OperationalStatus => {
  if (order.operationalStatus) return order.operationalStatus as OperationalStatus
  if (isCancelled(order)) return 'Cancelled'
  if (isDelivered(order)) return 'Delivered'
  if (isShipped(order)) return 'Shipped'
  if (isBooked(order)) return 'Booked'
  if (isNdr(order)) return 'NDR'
  return order.payment === 'Prepaid'
    ? order.addressVerified ? 'Ready for Booking' : 'Address Verification Pending'
    : order.latestCallResult === 'Callback Requested' ? 'Callback Required'
      : order.latestCallResult === 'Confirmed' ? 'Ready for Booking'
        : order.latestCallResult === 'Wrong Number' ? 'Needs Review'
          : 'Call Pending'
}
