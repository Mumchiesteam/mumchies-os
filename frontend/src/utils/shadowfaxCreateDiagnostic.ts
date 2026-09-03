import type { Order, ShadowfaxHealthCheck } from '../services/orders'

export type ShadowfaxCreateTestAvailability = {
  canCreate: boolean
  blocker: string | null
}

export const getShadowfaxCreateTestAvailability = (order: Order, role: string | undefined, healthCheck: ShadowfaxHealthCheck | null): ShadowfaxCreateTestAvailability => {
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
  if (!['owner', 'admin'].includes(role || '')) return { canCreate: false, blocker: 'Admin role required' }
  if (String(order.fulfillmentStatus || '').toLowerCase() !== 'unfulfilled') return { canCreate: false, blocker: 'Order already fulfilled' }
  if (shipmentEvidence) return { canCreate: false, blocker: 'Order already has shipment evidence' }
  if (!packageReady) return { canCreate: false, blocker: 'Package details missing' }
  if (healthCheck?.overall !== 'PASS') return { canCreate: false, blocker: 'Shadowfax health check not passing' }
  return { canCreate: true, blocker: null }
}

export const canTestShadowfaxCreate = (order: Order, role: string | undefined, healthCheck: ShadowfaxHealthCheck | null): boolean => getShadowfaxCreateTestAvailability(order, role, healthCheck).canCreate
