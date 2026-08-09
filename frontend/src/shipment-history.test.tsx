import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { ShipmentHistory } from './components/ShipmentHistory'
import { getShipmentEventHistory, type ShipmentEvent } from './services/shipmentEvents'
import { shipmentEventTime, shipmentEventTone, shipmentStatusLabel, uniqueNewestShipmentEvents } from './utils/shipmentHistory'

const event = (overrides: Partial<ShipmentEvent>): ShipmentEvent => ({
  id: 'event-1', order_id: 'order-1', order_number: '324600', shipment_reference: 'shipment-1',
  provider: 'shiprocket', courier_service: 'Ekart Surface', awb: 'AWB-1',
  provider_status_code: 'IT', normalized_status: 'in_transit', provider_event_at: '2026-08-02T10:00:00Z',
  recorded_at: '2026-08-02T10:05:00Z', location: 'Kolkata', message: null, reason: null,
  source: 'api_poll', deduplication_key: 'key-1', ...overrides,
})

describe('Shipment History', () => {
  it('is collapsed by default and contains the expandable history', () => {
    const html = renderToStaticMarkup(<ShipmentHistory orderId="order-1" privileged={false} initialEvents={[event({})]} />)
    expect(html).toContain('<details')
    expect(html).not.toContain('<details open=""')
    expect(html).toContain('Shipment History')
    expect(html).toContain('In Transit')
  })

  it('sorts newest first and suppresses duplicate provider events', () => {
    const values = uniqueNewestShipmentEvents([
      event({ id: 'old', deduplication_key: 'old', normalized_status: 'booked', provider_event_at: '2026-08-01T10:00:00Z' }),
      event({ id: 'new', deduplication_key: 'new', normalized_status: 'delivered', provider_event_at: '2026-08-03T10:00:00Z' }),
      event({ id: 'duplicate', deduplication_key: 'new', normalized_status: 'delivered', provider_event_at: '2026-08-03T10:00:00Z' }),
    ])
    expect(values.map(value => value.id)).toEqual(['new', 'old'])
  })

  it('prefers provider time and falls back to recorded time', () => {
    expect(shipmentEventTime(event({}))).toBe('2026-08-02T10:00:00Z')
    expect(shipmentEventTime(event({ provider_event_at: null }))).toBe('2026-08-02T10:05:00Z')
  })

  it('uses normalized labels and restrained exception/success tones', () => {
    expect(shipmentStatusLabel('pickup_scheduled')).toBe('Pickup Scheduled')
    expect(shipmentStatusLabel('rto_delivered')).toBe('RTO Delivered')
    expect(shipmentEventTone('ndr')).toContain('rose')
    expect(shipmentEventTone('rto_in_transit')).toContain('rose')
    expect(shipmentEventTone('delivered')).toContain('emerald')
    expect(shipmentEventTone('in_transit')).toContain('slate')
  })

  it('shows the underlying courier, optional details, and privileged summary', () => {
    const html = renderToStaticMarkup(<ShipmentHistory orderId="order-1" privileged initialEvents={[
      event({ location: null, message: null, reason: null }),
      event({ id: 'ndr', deduplication_key: 'ndr', normalized_status: 'ndr', provider_event_at: '2026-08-03T10:00:00Z', location: 'Kolkata Hub', reason: 'Customer unavailable', message: 'Delivery failed' }),
    ]} />)
    expect(html).toContain('Ekart Surface')
    expect(html).toContain('Kolkata Hub · Customer unavailable · Delivery failed')
    expect(html).toContain('Events recorded:')
    expect(html).toContain('AWB-1')
    expect(html).toContain('>—<')
  })

  it('shows the no-events state', () => {
    const html = renderToStaticMarkup(<ShipmentHistory orderId="order-1" privileged={false} initialEvents={[]} />)
    expect(html).toContain('No shipment history recorded yet.')
  })

  it('loads the authenticated read-only event endpoint used on expansion', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ order_id: 'order/1', events: [], total: 0 }), { status: 200 }))
    await getShipmentEventHistory('order/1')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/couriers/orders/order%2F1/events')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
  })
})
