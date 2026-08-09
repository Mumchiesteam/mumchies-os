import { apiBase, apiFetch } from './orders'

export type ShipmentEvent = {
  id: string
  order_id: string
  order_number: string | null
  shipment_reference: string | null
  provider: string
  courier_service: string | null
  awb: string | null
  provider_status_code: string | null
  normalized_status: string
  provider_event_at: string | null
  recorded_at: string
  location: string | null
  message: string | null
  reason: string | null
  source: string
  deduplication_key: string
}

export type ShipmentEventHistory = { order_id: string; events: ShipmentEvent[]; total: number }

export async function getShipmentEventHistory(orderId: string): Promise<ShipmentEventHistory> {
  const response = await apiFetch(`${apiBase}/api/v1/couriers/orders/${encodeURIComponent(orderId)}/events`)
  if (!response.ok) throw new Error(`Unable to load shipment history (${response.status})`)
  return response.json()
}
