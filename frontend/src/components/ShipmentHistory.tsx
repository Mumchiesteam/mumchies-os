import { useMemo, useState } from 'react'
import { getShipmentEventHistory, type ShipmentEvent } from '../services/shipmentEvents'
import { formatDateTime } from '../utils/time'
import { shipmentEventTime, shipmentEventTone, shipmentStatusLabel, uniqueNewestShipmentEvents } from '../utils/shipmentHistory'

export function ShipmentHistory({ orderId, privileged, initialEvents }: { orderId: string; privileged: boolean; initialEvents?: ShipmentEvent[] }) {
  const [events, setEvents] = useState<ShipmentEvent[] | null>(initialEvents ?? null)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const ordered = useMemo(() => uniqueNewestShipmentEvents(events || []), [events])
  const load = () => {
    if (events !== null || loading) return
    setLoading(true)
    setError('')
    void getShipmentEventHistory(orderId)
      .then(result => setEvents(result.events))
      .catch(reason => setError(reason instanceof Error ? reason.message : 'Unable to load shipment history.'))
      .finally(() => setLoading(false))
  }
  const first = ordered.length ? ordered[ordered.length - 1] : null
  const latest = ordered[0] || null
  const summaryProvider = latest?.provider || '—'
  const summaryAwb = latest?.awb || '—'

  return <details onToggle={event => { if (event.currentTarget.open) load() }} className="rounded-lg border border-slate-200 bg-white px-3 py-2">
    <summary className="cursor-pointer text-sm font-semibold text-slate-700">Shipment History</summary>
    <div className="mt-3">
      {loading && <p className="text-xs text-slate-500">Loading shipment history…</p>}
      {error && <p role="alert" className="rounded-md bg-rose-50 px-2 py-1.5 text-xs text-rose-700">{error}</p>}
      {!loading && !error && events !== null && ordered.length === 0 && <p className="text-sm text-slate-500">No shipment history recorded yet.</p>}
      {ordered.length > 0 && <div className="overflow-x-auto"><table className="w-full text-left text-xs">
        <thead className="border-b border-slate-200 text-[10px] uppercase tracking-wide text-slate-400"><tr><th className="pb-2 pr-3">Date &amp; Time</th><th className="pb-2 pr-3">Status</th><th className="pb-2 pr-3">Courier</th><th className="pb-2">Location / Detail</th></tr></thead>
        <tbody>{ordered.map(event => {
          const detail = [event.location, event.reason, event.message].filter(Boolean).filter((value, index, values) => values.indexOf(value) === index).join(' · ')
          return <tr key={event.deduplication_key || event.id} className={`border-b last:border-0 ${shipmentEventTone(event.normalized_status)}`}>
            <td className="whitespace-nowrap py-2 pr-3">{formatDateTime(shipmentEventTime(event))}</td>
            <td className="py-2 pr-3 font-semibold">{shipmentStatusLabel(event.normalized_status)}</td>
            <td className="py-2 pr-3">{event.courier_service || event.provider}</td>
            <td className="py-2">{detail || '—'}</td>
          </tr>
        })}</tbody>
      </table></div>}
      {privileged && events !== null && <div className="mt-3 grid gap-x-4 gap-y-1 rounded-md bg-slate-50 px-2 py-2 text-[11px] text-slate-500 sm:grid-cols-2">
        <span>Events recorded: <strong className="text-slate-700">{ordered.length}</strong></span>
        <span>Provider: <strong className="text-slate-700">{summaryProvider}</strong></span>
        <span>First event: <strong className="text-slate-700">{first ? formatDateTime(shipmentEventTime(first)) : '—'}</strong></span>
        <span>AWB: <strong className="text-slate-700">{summaryAwb}</strong></span>
        <span>Latest event: <strong className="text-slate-700">{latest ? formatDateTime(shipmentEventTime(latest)) : '—'}</strong></span>
      </div>}
    </div>
  </details>
}
