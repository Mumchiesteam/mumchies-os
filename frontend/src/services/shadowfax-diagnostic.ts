import { apiBase, apiErrorMessage, type Order } from './orders'

export type ShadowfaxHealth = {
  configured: boolean
  authenticated: boolean
  serviceability_available: boolean
}

export type ShadowfaxCreateTestResult = {
  outcome: string
  http_status: number | null
  message: string | null
  validation_errors: unknown
  data: { id: string | null; awb_number: string | null }
  payload: Record<string, unknown>
}

export const canTestShadowfaxCreate = (order: Order, health: ShadowfaxHealth | null, role: string | undefined) => {
  const packageDetails = order.packageDetails
  const packageReady = Boolean(packageDetails && [packageDetails.weight_kg, packageDetails.length_cm, packageDetails.breadth_cm, packageDetails.height_cm].every(value => typeof value === 'number' && value > 0))
  return (role === 'owner' || role === 'admin')
    && String(order.fulfillmentStatus || '').toLowerCase() === 'unfulfilled'
    && !order.shipment?.awb
    && !order.externalTracking?.awb
    && !order.shipment?.shipment_id
    && packageReady
    && health?.configured === true
    && health.authenticated === true
    && health.serviceability_available === true
}

export async function getShadowfaxHealth(): Promise<ShadowfaxHealth> {
  const response = await fetch(`${apiBase}/api/v1/couriers/shadowfax/health`, { credentials: 'include' })
  if (!response.ok) throw new Error('Shadowfax diagnostic availability could not be checked.')
  return response.json()
}

export async function testShadowfaxCreateOrder(orderId: string): Promise<ShadowfaxCreateTestResult> {
  const response = await fetch(`${apiBase}/api/v1/shadowfax/test-create-order/${orderId}`, { method: 'POST', credentials: 'include' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(apiErrorMessage(body, 'Shadowfax create test failed.'))
  return body
}
