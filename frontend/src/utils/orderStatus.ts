import type { Order } from '../services/orders'

export type OperationalStatus = 'Call Pending' | 'Callback Required' | 'Address Verification Pending' | 'Ready for Booking' | 'Booked' | 'Shipped' | 'NDR' | 'Delivered' | 'Cancelled' | 'Needs Review'

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
export const isBooked = (order: Order) => Boolean(order.shipment?.awb || order.shipment?.shipment_id)

export const hasShipmentEvidence = (order: Order) => isBooked(order) || Boolean(order.externalTracking?.awb)

export const listStatus = (order: Order): OperationalStatus => {
  if (isCancelled(order)) return 'Cancelled'
  if (isDelivered(order)) return 'Delivered'
  if (isShipped(order)) return 'Shipped'
  if (isBooked(order)) return 'Booked'
  if (isNdr(order)) return 'NDR'
  const isVerified = order.addressVerified || ['verified', 'completed', 'complete', 'approved'].includes(order.addressVerificationStatus?.toLowerCase() || '')
  if (order.payment === 'Prepaid') {
    return isVerified ? 'Ready for Booking' : 'Address Verification Pending'
  }
  if (order.operationalStatus && !(isVerified && order.operationalStatus === 'Address Verification Pending')) {
    return order.operationalStatus as OperationalStatus
  }
  return order.latestCallResult === 'Callback Requested' ? 'Callback Required'
    : order.latestCallResult === 'Confirmed' ? 'Ready for Booking'
      : order.latestCallResult === 'Wrong Number' ? 'Needs Review'
        : 'Call Pending'
}
