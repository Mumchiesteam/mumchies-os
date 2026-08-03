import type { Order } from '../services/orders'

export type OperationalStatus = 'Call Pending' | 'Callback Required' | 'On Hold' | 'Address Verification Pending' | 'Ready for Booking' | 'Booked' | 'Shipped' | 'NDR' | 'Delivered' | 'Cancelled' | 'Needs Review'

export const isCancelled = (order: Order) => Boolean(order.cancelledAt || order.shopifyStatus === 'cancelled' || (order.payment === 'COD' && order.tags.join(' ').toLowerCase().includes('cancel')))
const isShipped = (order: Order) => {
  const ful = (order.fulfillmentStatus || '').toLowerCase()
  const shopifySt = (order.shopifyStatus || '').toLowerCase()
  const trackingSt = (order.externalTracking?.status || '').toLowerCase()
  const tagsStr = order.tags.join(' ').toLowerCase()
  if (ful === 'unfulfilled') {
    const shippedKeywords = ['shipped', 'picked up', 'dispatched', 'in transit', 'out for delivery']
    return shippedKeywords.some(k => trackingSt.includes(k) || tagsStr.includes(k)) || Boolean(order.externalTracking?.awb)
  }
  const isFulfilled = ful === 'fulfilled' || ful === 'shipped' || ful === 'partially_fulfilled' || shopifySt === 'fulfilled' || shopifySt === 'shipped'
  const shippedKeywords = ['shipped', 'picked up', 'dispatched', 'in transit', 'out for delivery']
  const isTrackingShipped = shippedKeywords.some(k => trackingSt.includes(k) || tagsStr.includes(k))
  return isFulfilled || isTrackingShipped || Boolean(order.externalTracking?.awb)
}
const isDelivered = (order: Order) => `${order.fulfillmentStatus || ''} ${order.shopifyStatus || ''} ${order.tags.join(' ')} ${order.externalTracking?.status || ''}`.toLowerCase().includes('delivered')
const isNdr = (order: Order) => `${order.tags.join(' ')} ${order.shopifyStatus || ''}`.toLowerCase().includes('ndr')
export const isBooked = (order: Order) => {
  const shipment = order.shipment
  if (!shipment) return false
  if (shipment.awb || shipment.shopify_tracking_number || shipment.shipment_id) return true
  return Boolean(shipment.provider_order_id && ['booked', 'complete', 'completed', 'awb_assigned'].includes(String(shipment.booking_status || '').toLowerCase()))
}

export const hasShipmentEvidence = (order: Order) => isBooked(order) || Boolean(order.externalTracking?.awb)

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
