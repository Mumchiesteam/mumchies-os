import type { Order, ShadowfaxHealthCheck } from '../services/orders'

export const canTestShadowfaxCreate = (order: Order, role: string | undefined, healthCheck: ShadowfaxHealthCheck | null): boolean => {
  const shipment = order.shipment
  const packageDetails = order.packageDetails
  const packageReady = Boolean(
    packageDetails
    && Number(packageDetails.weight_kg) > 0
    && Number(packageDetails.length_cm) > 0
    && Number(packageDetails.breadth_cm) > 0
    && Number(packageDetails.height_cm) > 0,
  )
  const shipmentEvidence = Boolean(
    order.externalTracking?.awb
    || shipment?.awb
    || shipment?.shipment_id
    || shipment?.provider_order_id,
  )
  return ['owner', 'admin'].includes(role || '')
    && String(order.fulfillmentStatus || '').toLowerCase() === 'unfulfilled'
    && !shipmentEvidence
    && packageReady
    && healthCheck?.overall === 'PASS'
}
