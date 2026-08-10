import { useEffect, useState } from 'react'
import { getPollerHealth, type PollerHealth } from '../services/poller-health'

const display = (value: string) => value.replaceAll('_', ' ').replace(/\b\w/g, letter => letter.toUpperCase())
const percent = (success: number, attempted: number) => attempted ? `${((success * 100) / attempted).toFixed(1)}%` : '—'
const when = (value?: string | null) => value ? new Date(value).toLocaleString('en-IN') : '—'

export function TrackingPollerHealth() {
  const [data, setData] = useState<PollerHealth | null>(null)
  const [error, setError] = useState('')
  useEffect(() => {
    let active = true
    void getPollerHealth().then(value => { if (active) setData(value) }).catch(reason => { if (active) setError(reason.message) })
    return () => { active = false }
  }, [])
  if (error) return <section aria-label="Tracking Poller Health" className="mt-4 rounded-xl border bg-white p-3"><h3 className="text-sm font-bold">Tracking Poller Health</h3><p role="alert" className="mt-2 text-xs text-rose-700">{error}</p></section>
  if (!data) return <section aria-label="Tracking Poller Health" className="mt-4 rounded-xl border bg-white p-3"><h3 className="text-sm font-bold">Tracking Poller Health</h3><p className="mt-2 text-xs text-slate-500">Loading poller diagnostics…</p></section>
  return <TrackingPollerHealthView data={data} />
}

export function TrackingPollerHealthView({ data }: { data: PollerHealth }) {
  const latest = data.audit.latest_runs[0]
  const started = latest?.started_at || data.last_poll_started
  const completed = latest?.completed_at || data.last_poll_completed
  const duration = started && completed ? Math.max(0, (new Date(completed).getTime() - new Date(started).getTime()) / 1000) : null
  const attempted = latest?.total_attempted ?? data.shipments_attempted ?? 0
  const succeeded = latest?.total_succeeded ?? data.shipments_succeeded ?? 0
  const failed = latest?.total_failed ?? data.shipments_failed ?? 0
  const events = latest?.new_events_persisted ?? data.new_events_persisted ?? 0
  const providers = latest?.provider_counts || data.provider_stats || {}
  const latestFailures = latest ? data.audit.failed_shipments.filter(row => row.run_id === latest.run_id) : data.audit.failed_shipments
  return <section aria-label="Tracking Poller Health" className="mt-4 rounded-xl border bg-white p-3">
    <div className="flex flex-wrap items-baseline justify-between gap-2"><div><h3 className="text-sm font-bold">Tracking Poller Health</h3><p className="text-[11px] text-slate-500">Owner/Admin diagnostics · read-only</p></div><span className={`rounded-full px-2 py-1 text-[10px] font-semibold ${data.enabled ? 'bg-emerald-50 text-emerald-700' : 'bg-slate-100 text-slate-500'}`}>{data.enabled ? 'Enabled' : 'Disabled'}</span></div>
    <div className="mt-2 grid grid-cols-2 gap-2 text-xs md:grid-cols-4 xl:grid-cols-7">
      {[['Latest run', when(started)], ['Duration', duration == null ? '—' : `${duration.toFixed(1)}s`], ['Attempted', attempted], ['Successful', succeeded], ['Failed', failed], ['Success', percent(succeeded, attempted)], ['New events', events]].map(([label, value]) => <div key={label} className="rounded bg-slate-50 p-2"><p className="text-[10px] text-slate-400">{label}</p><b>{value}</b></div>)}
    </div>
    <div className="mt-3 grid gap-3 xl:grid-cols-2">
      <div className="overflow-x-auto"><h4 className="text-xs font-bold">Provider split</h4><table className="mt-1 w-full text-xs"><thead className="text-left text-slate-400"><tr><th>Provider</th><th>Attempted</th><th>Success</th><th>Failed</th><th>Success %</th><th>Events</th></tr></thead><tbody>{['shiprocket', 'delhivery'].map(provider => { const row = providers[provider] || { attempted: 0, succeeded: 0, failed: 0, new_events: 0 }; return <tr key={provider} className="border-t"><td className="py-1.5 font-semibold">{display(provider)}</td><td>{row.attempted}</td><td>{row.succeeded}</td><td>{row.failed}</td><td>{percent(row.succeeded, row.attempted)}</td><td>{row.new_events || 0}</td></tr> })}</tbody></table></div>
      <div><h4 className="text-xs font-bold">Failure breakdown</h4><div className="mt-1 flex flex-wrap gap-1.5">{Object.entries(data.audit.failure_breakdown).length ? Object.entries(data.audit.failure_breakdown).map(([category, count]) => <span key={category} className="rounded bg-rose-50 px-2 py-1 text-xs text-rose-700">{display(category)}: <b>{count}</b></span>) : <span className="text-xs text-slate-500">No retained failures.</span>}</div></div>
    </div>
    <div className="mt-3 overflow-x-auto"><h4 className="text-xs font-bold">Latest failed shipments</h4><table className="mt-1 w-full min-w-[720px] text-xs"><thead className="text-left text-slate-400"><tr><th>Order</th><th>Provider</th><th>Courier</th><th>AWB</th><th>Error category</th><th>HTTP</th></tr></thead><tbody>{latestFailures.length ? latestFailures.map((row, index) => <tr key={`${row.run_id}-${row.order_id}-${index}`} className="border-t"><td className="py-1.5">{row.order_number || row.order_id || '—'}</td><td>{display(row.provider)}</td><td>{row.courier_service || '—'}</td><td>{row.awb_reference || '—'}</td><td>{display(row.error_category || 'other')}</td><td>{row.http_status ?? '—'}</td></tr>) : <tr><td colSpan={6} className="py-2 text-slate-500">No failed shipments in the latest run.</td></tr>}</tbody></table></div>
    <div className="mt-3 grid gap-3 xl:grid-cols-2">
      <div><h4 className="text-xs font-bold">Event count by provider</h4><div className="mt-1 flex gap-2 text-xs">{Object.entries(data.audit.event_count_by_provider).map(([provider, count]) => <span key={provider} className="rounded bg-slate-50 px-2 py-1">{display(provider)}: <b>{count}</b></span>)}</div></div>
      <div><h4 className="text-xs font-bold">Lifecycle coverage</h4><div className="mt-1 space-y-1 text-xs">{Object.entries(data.audit.lifecycle_coverage).map(([provider, statuses]) => <p key={provider}><b>{display(provider)}:</b> {Object.entries(statuses).map(([status, count]) => `${display(status)} ${count}`).join(' · ')}</p>)}</div></div>
    </div>
  </section>
}
