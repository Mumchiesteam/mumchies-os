import { useMemo, useState } from 'react'
import { formatMoney } from '../services/orders'
import { sortGeographyRows, type Comparison, type GeographyData, type GeographyProduct, type GeographyRow } from '../services/analytics'
import { kpiComparisonTone, semanticTextClass, deltaTone } from '../utils/semanticFormatting'

const KPI: [string, string, 'money' | 'number' | 'rate'][] = [
  ['orders', 'Orders', 'number'], ['active_orders', 'Active Orders', 'number'], ['order_value', 'Order Value', 'money'],
  ['aov', 'AOV', 'money'], ['customers', 'Customers', 'number'], ['repeat_percent', 'Repeat Customer', 'rate'],
  ['cod_percent', 'COD', 'rate'], ['prepaid_percent', 'Prepaid', 'rate'],
]
const numericColumns: [keyof GeographyRow, string][] = [['orders', 'Orders'], ['order_value', 'Order Value'], ['aov', 'AOV'], ['customers', 'Customers'], ['repeat_percent', 'Repeat %'], ['cod_percent', 'COD %'], ['prepaid_percent', 'Prepaid %'], ['orders_change', 'Δ Orders'], ['value_change', 'Δ Value'], ['aov_change', 'Δ AOV'], ['repeat_points', 'Δ Repeat pp']]

const show = (amount: number, kind: string) => kind === 'money' ? formatMoney(amount) : kind === 'rate' ? `${amount}%` : String(amount)
const comparison = (key: string, item?: Comparison) => {
  if (!item) return <span className="text-slate-500">—</span>
  const text = item.points != null ? `${item.points >= 0 ? '+' : ''}${item.points} pp` : item.percent == null ? `${item.absolute >= 0 ? '+' : ''}${item.absolute}` : `${item.percent >= 0 ? '+' : ''}${item.percent}%`
  return <span className={semanticTextClass[kpiComparisonTone(key, item)]}>{text}</span>
}

export function GeographyAnalytics({ data, showDataQuality = false }: { data: GeographyData; showDataQuality?: boolean }) {
  const [state, setState] = useState<string | null>(null)
  const [city, setCity] = useState<string | null>(null)
  const [sortKey, setSortKey] = useState<keyof GeographyRow>('order_value')
  const [descending, setDescending] = useState(true)
  const level = city ? 'pincode' : state ? 'city' : 'state'
  const sorted = useMemo(() => {
    const rows = level === 'state' ? data.states : level === 'city' ? data.cities[state || ''] || [] : data.pincodes[`${state}|${city}`] || []
    return sortGeographyRows(rows, sortKey, descending)
  }, [data, level, state, city, sortKey, descending])
  const productsKey = city ? `city:${state}|${city}` : state ? `state:${state}` : 'all'
  const products = data.products[productsKey] || []
  const chooseSort = (key: keyof GeographyRow) => { if (sortKey === key) setDescending(value => !value); else { setSortKey(key); setDescending(true) } }
  return <>
    <section><h3 className="mb-2 text-xs font-bold uppercase tracking-wider text-slate-400">Geography Performance</h3><div className="grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-8">{KPI.map(([key, label, kind]) => <div key={key} className="rounded-lg border bg-white p-2.5"><p className="text-[10px] font-semibold text-slate-400">{label}</p><p className="text-lg font-bold">{show(data.summary[key] || 0, kind)}</p><p className="text-[10px]">{comparison(key, data.comparisons[key])} vs previous</p></div>)}</div></section>
    <section className="mt-4 overflow-x-auto rounded-xl border bg-white">
      <div className="flex flex-wrap items-center justify-between gap-2 border-b p-3"><div><h3 className="text-sm font-bold">{level === 'state' ? 'State Performance' : level === 'city' ? 'City Performance' : 'Pincode Performance'}</h3><nav aria-label="Geography breadcrumb" className="mt-1 text-xs"><button className="font-semibold text-orange-600" onClick={() => { setState(null); setCity(null) }}>All India</button>{state && <> <span>›</span> <button className="font-semibold text-orange-600" onClick={() => setCity(null)}>{state}</button></>}{city && <> <span>›</span> <span>{city}</span></>}</nav></div>{showDataQuality && <p className="rounded bg-amber-50 px-2 py-1 text-[10px] text-amber-800">Missing State: {data.data_quality.missing_state} · City: {data.data_quality.missing_city} · Pincode: {data.data_quality.missing_pincode}</p>}</div>
      <table className="w-full min-w-[1100px] text-xs"><thead className="bg-slate-50 text-left text-slate-400"><tr><th className="p-2">{level === 'state' ? 'State' : level === 'city' ? 'City' : 'Pincode'}</th>{numericColumns.filter(([key]) => level !== 'pincode' || !['orders_change', 'value_change', 'aov_change', 'repeat_points'].includes(key)).map(([key, label]) => <th key={key}><button className="font-semibold" onClick={() => chooseSort(key)}>{label}{sortKey === key ? descending ? ' ↓' : ' ↑' : ''}</button></th>)}</tr></thead><tbody>{sorted.map(row => { const name = String(row[level] || 'Unknown'); return <tr key={name} className="border-t"><td className="p-2 font-semibold">{level === 'pincode' ? name : <button className="text-orange-700 hover:underline" onClick={() => level === 'state' ? (setState(name), setCity(null)) : setCity(name)}>{name}</button>}</td>{numericColumns.filter(([key]) => level !== 'pincode' || !['orders_change', 'value_change', 'aov_change', 'repeat_points'].includes(key)).map(([key]) => <td key={key} className={['orders_change', 'value_change', 'aov_change', 'repeat_points'].includes(key) ? semanticTextClass[deltaTone(Number(row[key]))] : ''}>{key.includes('value') || key === 'aov' || key === 'aov_change' ? formatMoney(Number(row[key])) : key.includes('percent') || key === 'repeat_points' ? `${row[key]}${key === 'repeat_points' ? ' pp' : '%'}` : row[key]}</td>)}</tr>})}</tbody></table>
    </section>
    <GeographyProducts products={products} />
  </>
}

function GeographyProducts({ products }: { products: GeographyProduct[] }) {
  return <section className="mt-4 overflow-x-auto rounded-xl border bg-white"><h3 className="p-3 text-sm font-bold">Top Products in Selected Geography</h3><table className="w-full min-w-[800px] text-xs"><thead className="bg-slate-50 text-left text-slate-400"><tr><th className="p-2">Product</th><th>Orders</th><th>Qty</th><th>Order Value</th><th>Order %</th><th>Repeat Orders</th><th>Δ Orders</th><th>Δ Value</th></tr></thead><tbody>{products.map(row => <tr key={row.product} className="border-t"><td className="p-2 font-semibold">{row.product}</td><td>{row.orders}</td><td>{row.quantity}</td><td>{formatMoney(row.value)}</td><td>{row.order_percent}%</td><td>{row.repeat_orders}</td><td className={semanticTextClass[deltaTone(row.order_change)]}>{row.order_change}</td><td className={semanticTextClass[deltaTone(row.value_change)]}>{formatMoney(row.value_change)}</td></tr>)}</tbody></table></section>
}
