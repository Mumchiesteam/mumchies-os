export type SemanticTone = 'positive' | 'warning' | 'negative' | 'neutral'

type Comparison = { percent: number | null; points: number | null }

const HIGHER_IS_FAVOURABLE = new Set([
  'total_orders', 'orders', 'active_orders', 'order_value', 'aov', 'customers',
  'fulfilled_orders', 'fulfillment_percent', 'repeat_percent',
])

export function kpiComparisonTone(key: string, comparison?: Comparison): SemanticTone {
  if (!comparison || key === 'items_per_order') return 'neutral'
  const movement = comparison.points ?? comparison.percent
  const threshold = comparison.points != null ? 0.5 : 1
  if (movement == null || Math.abs(movement) < threshold) return 'neutral'
  if (key !== 'cancellation_percent' && !HIGHER_IS_FAVOURABLE.has(key)) return 'neutral'
  const favourable = key === 'cancellation_percent' ? movement < 0 : movement > 0
  return favourable ? 'positive' : 'negative'
}

export function cancellationTone(rate: number): SemanticTone {
  if (rate < 5) return 'positive'
  if (rate <= 10) return 'warning'
  return 'negative'
}

export function deltaTone(value: number): SemanticTone {
  return value > 0 ? 'positive' : value < 0 ? 'negative' : 'neutral'
}

export function attentionTone(key: string, count: number | null | undefined): SemanticTone {
  if (!count || count < 1) return 'neutral'
  if (key === 'ndr_over_sla' || key === 'reconciliation_exceptions') return 'negative'
  if (key === 'follow_up' || key === 'on_hold' || key === 'ready_booking') return 'warning'
  return 'neutral'
}

export const semanticTextClass: Record<SemanticTone, string> = {
  positive: 'text-emerald-700', warning: 'text-amber-700', negative: 'text-rose-700', neutral: 'text-slate-500',
}

export const attentionClass: Record<SemanticTone, string> = {
  positive: 'border-emerald-200 bg-emerald-50/40 hover:border-emerald-300',
  warning: 'border-amber-200 bg-amber-50/40 hover:border-amber-300',
  negative: 'border-rose-200 bg-rose-50/40 hover:border-rose-300',
  neutral: 'border-slate-200 bg-white hover:border-orange-300',
}
