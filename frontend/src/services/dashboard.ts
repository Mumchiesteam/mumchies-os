import { apiBase, apiFetch } from './orders'
import type { PeriodPreset } from '../components/PeriodSelector'

export type DashboardPreset = PeriodPreset
export type DashboardData = {
  last_refreshed_at?: string | null
  refresh_error?: string | null
  refreshing?: boolean
  period: { preset: DashboardPreset; start: string; end: string; label: string }
  needs_attention: { fresh: number; follow_up: number; on_hold: number; ready_booking: number; active_ndr: number; ndr_over_sla: number; reconciliation_exceptions: number | null }
  team_activity: { operators: { operator: string; orders_actioned: number; ndrs_actioned: number }[]; total: { orders_actioned: number; ndrs_actioned: number } }
  orders: { total: number; value: number; repeat_percent: number; actioned: number; pending: number; cancelled_excluded: number }
  payment_mix: Record<'cod' | 'prepaid' | 'partial_cod', { count: number; percent: number }>
  top_products: { product: string; quantity: number; orders: number; order_value: number }[]
}

export async function getDashboard(preset: DashboardPreset, start?: string, end?: string, refresh = false): Promise<DashboardData> {
  const query = new URLSearchParams({ preset })
  if (refresh) query.set('refresh', 'true')
  if (preset === 'custom' && start && end) { query.set('start', start); query.set('end', end) }
  const response = await apiFetch(`${apiBase}/api/v1/dashboard?${query}`)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : `Dashboard request failed (HTTP ${response.status}).`)
  }
  return response.json()
}
