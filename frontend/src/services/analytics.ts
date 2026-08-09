import type { PeriodPreset } from '../components/PeriodSelector'
import { apiBase, apiFetch } from './orders'

export type AnalyticsData = { last_refreshed_at?: string; refresh_error?: string | null; refreshing?: boolean; period: { label: string }; business: Record<string, number>; comparisons: Record<string, { absolute: number; percent: number | null; points: number | null }>; customers: Record<string, number>; payment: { key: string; label: string; orders: number; percent: number; value: number; aov: number; cancellation_percent: number }[]; products: { product: string; quantity: number; orders: number; value: number; order_percent: number; new_orders: number; repeat_orders: number; quantity_change: number; order_change: number; value_change: number }[]; trend: { granularity: string; points: { label: string; orders: number; revenue: number }[] } }

export async function getAnalytics(preset: PeriodPreset, start: string, end: string, payment: string, customer: string, refresh = false): Promise<AnalyticsData> {
  const query = new URLSearchParams({ preset, payment, customer }); if (preset === 'custom') { query.set('start', start); query.set('end', end) }; if (refresh) query.set('refresh', 'true')
  const response = await apiFetch(`${apiBase}/api/v1/analytics?${query}`); const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : `Analytics request failed (${response.status}).`)
  return body
}
