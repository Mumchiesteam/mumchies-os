import type { ShipmentEvent } from '../services/shipmentEvents'

const labels: Record<string, string> = {
  booked: 'Booked', pickup_scheduled: 'Pickup Scheduled', picked_up: 'Picked Up',
  in_transit: 'In Transit', out_for_delivery: 'Out for Delivery',
  delivery_attempted: 'Delivery Attempted', ndr: 'NDR', reattempt: 'Reattempt',
  delivered: 'Delivered', rto_initiated: 'RTO Initiated',
  rto_in_transit: 'RTO In Transit', rto_delivered: 'RTO Delivered',
  cancelled: 'Cancelled', unknown: 'Unknown',
}

export const shipmentStatusLabel = (status: string) => labels[status] || status.replaceAll('_', ' ').replace(/\b\w/g, value => value.toUpperCase())
export const shipmentEventTime = (event: ShipmentEvent) => event.provider_event_at || event.recorded_at
export const shipmentEventTone = (status: string) => {
  if (status === 'delivered') return 'border-emerald-200 bg-emerald-50/50 text-emerald-800'
  if (status === 'ndr' || status.startsWith('rto_')) return 'border-rose-200 bg-rose-50/50 text-rose-800'
  return 'border-slate-100 text-slate-700'
}
export function uniqueNewestShipmentEvents(events: ShipmentEvent[]): ShipmentEvent[] {
  const seen = new Set<string>()
  return [...events]
    .sort((left, right) => new Date(shipmentEventTime(right)).getTime() - new Date(shipmentEventTime(left)).getTime())
    .filter(event => {
      const key = event.deduplication_key || event.id
      if (seen.has(key)) return false
      seen.add(key)
      return true
    })
}
