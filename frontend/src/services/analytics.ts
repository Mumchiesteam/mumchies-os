import type { PeriodPreset } from '../components/PeriodSelector'
import { apiBase, apiFetch } from './orders'

export type Comparison = { absolute: number; percent: number | null; points: number | null }
export type GeographyRow = { state?: string; city?: string; pincode?: string; orders: number; active_orders: number; order_value: number; aov: number; customers: number; repeat_percent: number; cod_percent: number; prepaid_percent: number; orders_change: number; value_change: number; aov_change: number; repeat_points: number }
export type GeographyProduct = { product: string; orders: number; quantity: number; value: number; order_percent: number; repeat_orders: number; order_change: number; value_change: number }
export type GeographyData = { summary: Record<string, number>; comparisons: Record<string, Comparison>; states: GeographyRow[]; cities: Record<string, GeographyRow[]>; pincodes: Record<string, GeographyRow[]>; products: Record<string, GeographyProduct[]>; data_quality: { missing_state: number; missing_city: number; missing_pincode: number } }
export type AnalyticsData = { last_refreshed_at?: string; refresh_error?: string | null; refreshing?: boolean; period: { label: string }; business: Record<string, number>; comparisons: Record<string, Comparison>; customers: Record<string, number>; payment: { key: string; label: string; orders: number; percent: number; value: number; aov: number; cancellation_percent: number }[]; products: { product: string; quantity: number; orders: number; value: number; order_percent: number; new_orders: number; repeat_orders: number; quantity_change: number; order_change: number; value_change: number }[]; trend: { granularity: string; points: { label: string; orders: number; revenue: number }[] }; geography: GeographyData }

export const analyticsKpis: [string, string, 'money' | 'number' | 'rate'][] = [['total_orders', 'Total Orders', 'number'], ['active_orders', 'Active Orders', 'number'], ['order_value', 'Order Value', 'money'], ['aov', 'AOV', 'money'], ['items_per_order', 'Items / Order', 'number'], ['cancellation_percent', 'Cancellation', 'rate'], ['fulfilled_orders', 'Fulfilled Orders', 'number'], ['fulfillment_percent', 'Fulfilment', 'rate'], ['repeat_percent', 'Repeat Customer', 'rate']]

export function sortGeographyRows(rows: GeographyRow[], key: keyof GeographyRow, descending: boolean) {
  return [...rows].sort((a, b) => (Number(a[key] || 0) - Number(b[key] || 0)) * (descending ? -1 : 1))
}

export async function getAnalytics(preset: PeriodPreset, start: string, end: string, payment: string, customer: string, refresh = false): Promise<AnalyticsData> {
  const query = new URLSearchParams({ preset, payment, customer }); if (preset === 'custom') { query.set('start', start); query.set('end', end) }; if (refresh) query.set('refresh', 'true')
  const response = await apiFetch(`${apiBase}/api/v1/analytics?${query}`); const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `Analytics request failed (${response.status}).`)
  return body
}
