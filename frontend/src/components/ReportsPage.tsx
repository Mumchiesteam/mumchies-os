import { useEffect, useState } from 'react'

import { formatMoney } from '../services/orders'
import { finaliseGstReport, getFinalGstReport, getGstReport, gstReportDownloadUrl, type GstReport } from '../services/reports'


const currentMonth = () => new Date().toLocaleDateString('en-CA', { year: 'numeric', month: '2-digit', timeZone: 'Asia/Kolkata' })
const monthLabel = (month: string) => new Date(`${month}-01T00:00:00`).toLocaleDateString('en-IN', { month: 'long', year: 'numeric' })
const finalisedLabel = (value: string) => new Date(value).toLocaleString('en-IN', { dateStyle: 'medium', timeStyle: 'short', timeZone: 'Asia/Kolkata' })

export function ReportsPage({ path, navigate }: { path: string; navigate: (path: string) => void }) {
  if (path !== '/reports/gst') {
    return <div>
      <p className="text-sm font-medium text-[#ff6b35]">Reports</p>
      <h2 className="mt-1 text-2xl font-bold tracking-tight">Reports</h2>
      <p className="mt-2 text-sm text-slate-500">Financial and operational reporting for Mumchies.</p>
      <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        <button onClick={() => navigate('/reports/gst')} className="rounded-xl border border-slate-200 bg-white p-5 text-left shadow-sm transition hover:border-orange-300 hover:shadow-md">
          <div className="grid h-10 w-10 place-items-center rounded-lg bg-orange-50 text-lg font-bold text-[#ff6b35]">%</div>
          <h3 className="mt-4 text-lg font-bold text-slate-900">GST Report</h3>
          <p className="mt-1 text-sm text-slate-500">Monthly GST reconciliation for online sales</p>
          <p className="mt-4 text-sm font-semibold text-[#ff6b35]">Open report →</p>
        </button>
      </div>
    </div>
  }
  return <GstReportPage navigate={navigate} />
}

function GstReportPage({ navigate }: { navigate: (path: string) => void }) {
  const [month, setMonth] = useState(currentMonth())
  const [report, setReport] = useState<GstReport | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [confirming, setConfirming] = useState(false)

  useEffect(() => {
    let active = true
    void getFinalGstReport(month).then(value => { if (active) setReport(value) }).catch(value => { if (active) setError((value as Error).message) }).finally(() => { if (active) setLoading(false) })
    return () => { active = false }
  }, [month])

  const generate = async (options: { refresh?: boolean; regenerate?: boolean } = {}) => {
    setLoading(true); setError('')
    try { setReport(await getGstReport(month, options)) }
    catch (value) { setError((value as Error).message) }
    finally { setLoading(false) }
  }
  const finalise = async () => {
    if (!report) return
    setLoading(true); setError('')
    try { setReport(await finaliseGstReport(report.month, report.checksum)); setConfirming(false) }
    catch (value) { setError((value as Error).message); setConfirming(false) }
    finally { setLoading(false) }
  }
  const isFinal = report?.status === 'FINAL'
  const regeneratedDraft = report?.status === 'DRAFT' && Boolean(report.comparison_to_final)
  const cards = report ? [
    ['Delivered orders', report.summary.delivered_orders.toLocaleString('en-IN')],
    ['Gross sales', formatMoney(report.summary.gross_sales)],
    ['Taxable value', formatMoney(report.summary.taxable_value)],
    ['CGST', formatMoney(report.summary.cgst)], ['SGST', formatMoney(report.summary.sgst)],
    ['IGST', formatMoney(report.summary.igst)], ['Total GST', formatMoney(report.summary.total_gst)],
    ['Exceptions', report.summary.exceptions.toLocaleString('en-IN')],
  ] : []
  return <div>
    <button onClick={() => navigate('/reports')} className="mb-3 text-sm font-semibold text-slate-500 hover:text-slate-900">← All reports</button>
    <div className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="text-sm font-medium text-[#ff6b35]">Reports / GST</p><div className="mt-1 flex items-center gap-3"><h2 className="text-2xl font-bold tracking-tight">Monthly GST report</h2><StatusBadge status={report?.status || 'DRAFT'} /></div><p className="mt-1 text-sm text-slate-500">Online sales selected by actual Shopify delivery date.</p>{isFinal && report.finalised_at && <p className="mt-2 text-sm font-semibold text-emerald-700">Finalised on {finalisedLabel(report.finalised_at)}</p>}{regeneratedDraft && <p className="mt-2 text-sm font-semibold text-amber-700">Current Shopify draft compared with the preserved FINAL filing.</p>}</div>
      <div className="flex flex-wrap items-end gap-2">
        <label><span className="mb-1 block text-xs font-semibold text-slate-500">Month</span><input aria-label="Report month" type="month" max={currentMonth()} value={month} onChange={event => { setReport(null); setError(''); setLoading(true); setMonth(event.target.value) }} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm" /></label>
        {!isFinal && !regeneratedDraft && <><button disabled={loading || !month} onClick={() => void generate()} className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{loading ? 'Generating…' : 'Generate Report'}</button><button disabled={loading || !month} onClick={() => void generate({ refresh: true })} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 disabled:opacity-50">Refresh Data</button></>}
        {isFinal && <button disabled={loading} onClick={() => void generate({ regenerate: true })} className="rounded-lg border border-amber-300 bg-amber-50 px-4 py-2.5 text-sm font-semibold text-amber-800 disabled:opacity-50">Regenerate Draft</button>}
        {regeneratedDraft && <button disabled={loading} onClick={() => void getFinalGstReport(month).then(value => setReport(value))} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-700 disabled:opacity-50">Return to FINAL</button>}
        <DownloadButton report={report} />
        {report?.status === 'DRAFT' && !regeneratedDraft && <button disabled={loading || !report.can_finalise} title={report.finalisation_failures.join(' ')} onClick={() => setConfirming(true)} className="rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40">Finalise Report</button>}
      </div>
    </div>
    {error && <p role="alert" className="mt-4 rounded-lg bg-rose-50 px-4 py-3 text-sm text-rose-700">{error}</p>}
    {!report && !loading && <div className="mt-8 rounded-xl border border-dashed border-slate-300 bg-white px-6 py-12 text-center text-sm text-slate-500">Choose a month and generate the report.</div>}
    {report && <>
      {report.status === 'DRAFT' && report.finalisation_failures.length > 0 && <div className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900"><p className="font-semibold">This draft cannot be finalised yet.</p><ul className="mt-2 list-disc pl-5">{report.finalisation_failures.map(value => <li key={value}>{value}</li>)}</ul></div>}
      {report.comparison_to_final && <Comparison comparison={report.comparison_to_final} />}
      <section className="mt-6 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">{cards.map(([label, value]) => <div key={label} className="rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><p className="text-xs font-semibold text-slate-500">{label}</p><p className="mt-1 text-xl font-bold text-slate-900">{value}</p></div>)}</section>
      <section className="mt-6 overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"><div className="border-b border-slate-200 px-4 py-4"><h3 className="font-bold text-slate-900">State-wise GST</h3><p className="mt-1 text-xs text-slate-500">Karnataka uses CGST + SGST; other states use IGST.</p></div><div className="overflow-x-auto"><table className="min-w-full text-sm"><thead className="bg-slate-50 text-left text-xs uppercase tracking-wide text-slate-500"><tr>{['Place of Supply','GST Rate','Orders','Taxable Value','CGST','SGST','IGST','Invoice Value'].map(value => <th key={value} className="whitespace-nowrap px-4 py-3">{value}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{report.rows.map(row => <tr key={`${row['Place of Supply']}-${row['GST Rate']}`}><td className="px-4 py-3 font-medium">{row['Place of Supply']}</td><td className="px-4 py-3">{row['GST Rate']}</td><td className="px-4 py-3">{row.Orders}</td>{(['Taxable Value','CGST','SGST','IGST','Total Invoice Value'] as const).map(key => <td key={key} className="whitespace-nowrap px-4 py-3 text-right tabular-nums">{formatMoney(row[key])}</td>)}</tr>)}</tbody></table></div></section>
      <section className="mt-6 grid gap-4 lg:grid-cols-2"><div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="font-bold">Reconciliation</h3><dl className="mt-4 space-y-3 text-sm"><Metric label="Previous-month-created, delivered this month" value={`${report.reconciliation.previous_month_created_delivered.orders} orders · ${formatMoney(report.reconciliation.previous_month_created_delivered.value)}`} /><Metric label="This-month-created, delivered next month" value={`${report.reconciliation.selected_month_created_delivered_following.orders} orders · ${formatMoney(report.reconciliation.selected_month_created_delivered_following.value)}`} /><Metric label="Excluded after delivery" value={`${report.summary.excluded_orders} orders`} /><Metric label="Taxable value + GST" value={formatMoney(report.summary.taxable_value + report.summary.total_gst)} /></dl></div><div className="rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="font-bold">GST adjustments</h3><dl className="mt-4 space-y-3 text-sm"><Metric label="Original Shopify GST" value={formatMoney(report.adjustments.original_shopify_gst)} /><Metric label="Shipping GST extracted" value={formatMoney(report.adjustments.shipping_gst)} /><Metric label="Product GST corrections" value={formatMoney(report.adjustments.product_gst_corrections)} /></dl>{report.baseline_comparison && <p className={`mt-4 rounded-lg px-3 py-2 text-sm font-semibold ${report.baseline_comparison.matches ? 'bg-emerald-50 text-emerald-700' : 'bg-rose-50 text-rose-700'}`}>{report.baseline_comparison.matches ? 'July validated baseline matched.' : 'July baseline differs. Review before filing.'}</p>}</div></section>
      <section className="mt-6 rounded-xl border border-slate-200 bg-white p-5 shadow-sm"><h3 className="font-bold">Exceptions requiring manual review</h3>{report.exceptions.length ? <div className="mt-3 divide-y divide-slate-100">{report.exceptions.map(value => <div key={value.order_number} className="py-3 text-sm"><p className="font-semibold">Order {value.order_number} · {formatMoney(value.invoice_value)}</p><p className="text-slate-500">{value.reason} · delivered {value.delivered_date}</p></div>)}</div> : <p className="mt-3 text-sm text-emerald-700">No exceptions for this month.</p>}</section>
    </>}
    {confirming && report && <div className="fixed inset-0 z-50 grid place-items-center bg-slate-950/40 p-4"><div role="dialog" aria-modal="true" aria-labelledby="finalise-title" className="w-full max-w-lg rounded-2xl bg-white p-6 shadow-2xl"><h3 id="finalise-title" className="text-xl font-bold">Finalise {monthLabel(report.month)} GST Report?</h3><p className="mt-3 text-sm leading-6 text-slate-600">This will save the current GST calculation as the filing version for this month. Future Shopify changes will not alter this saved report.</p><div className="mt-6 flex justify-end gap-2"><button disabled={loading} onClick={() => setConfirming(false)} className="rounded-lg border border-slate-200 px-4 py-2.5 text-sm font-semibold">Cancel</button><button disabled={loading} onClick={() => void finalise()} className="rounded-lg bg-emerald-700 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-50">{loading ? 'Finalising…' : 'Finalise Report'}</button></div></div></div>}
  </div>
}

function StatusBadge({ status }: { status: 'DRAFT' | 'FINAL' }) { return <span className={`rounded-full px-2.5 py-1 text-xs font-bold tracking-wide ${status === 'FINAL' ? 'bg-emerald-100 text-emerald-800' : 'bg-amber-100 text-amber-800'}`}>{status}</span> }
function DownloadButton({ report }: { report: GstReport | null }) { const enabled = Boolean(report && report.summary.exceptions === 0 && !report.comparison_to_final); return <a aria-disabled={!enabled} onClick={event => { if (!enabled) event.preventDefault() }} href={enabled && report ? gstReportDownloadUrl(report.month) : '#'} className={`rounded-lg border px-4 py-2.5 text-sm font-semibold ${enabled ? 'border-slate-200 bg-white text-slate-700' : 'pointer-events-none border-slate-100 bg-slate-50 text-slate-300'}`}>{report?.status === 'FINAL' ? 'Download Final CSV' : 'Download CSV'}</a> }
function Comparison({ comparison }: { comparison: NonNullable<GstReport['comparison_to_final']> }) { const labels: Record<string, string> = { delivered_orders: 'Orders', taxable_value: 'Taxable value', cgst: 'CGST', sgst: 'SGST', igst: 'IGST', total_gst: 'Total GST', gross_sales: 'Gross sales' }; return <section className="mt-5 rounded-xl border border-amber-200 bg-amber-50 p-5"><h3 className="font-bold text-amber-950">Draft versus FINAL</h3><p className="mt-1 text-sm text-amber-800">The saved FINAL report remains unchanged.</p><div className="mt-4 overflow-x-auto"><table className="min-w-full text-sm"><thead><tr className="text-left text-xs uppercase text-amber-800"><th className="py-2">Metric</th><th className="px-3 py-2 text-right">FINAL</th><th className="px-3 py-2 text-right">Draft</th><th className="py-2 text-right">Difference</th></tr></thead><tbody>{Object.entries(comparison.fields).map(([key, value]) => <tr key={key} className="border-t border-amber-200"><td className="py-2 font-medium">{labels[key]}</td><td className="px-3 py-2 text-right">{key === 'delivered_orders' ? value.final : formatMoney(value.final)}</td><td className="px-3 py-2 text-right">{key === 'delivered_orders' ? value.draft : formatMoney(value.draft)}</td><td className="py-2 text-right font-semibold">{key === 'delivered_orders' ? value.difference : formatMoney(value.difference)}</td></tr>)}</tbody></table></div></section> }
function Metric({ label, value }: { label: string; value: string }) { return <div className="flex items-start justify-between gap-4"><dt className="text-slate-500">{label}</dt><dd className="text-right font-semibold text-slate-800">{value}</dd></div> }
