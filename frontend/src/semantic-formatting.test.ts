import { describe, expect, it } from 'vitest'
import { attentionTone, cancellationTone, deltaTone, kpiComparisonTone } from './utils/semanticFormatting'

describe('semantic conditional formatting', () => {
  it('handles favourable, unfavourable and neutral KPI movement', () => {
    expect(kpiComparisonTone('order_value', { percent: 4, points: null })).toBe('positive')
    expect(kpiComparisonTone('order_value', { percent: -4, points: null })).toBe('negative')
    expect(kpiComparisonTone('cancellation_percent', { percent: null, points: -2 })).toBe('positive')
    expect(kpiComparisonTone('cancellation_percent', { percent: null, points: 2 })).toBe('negative')
    expect(kpiComparisonTone('aov', { percent: 0.9, points: null })).toBe('neutral')
    expect(kpiComparisonTone('repeat_percent', { percent: null, points: 0.4 })).toBe('neutral')
    expect(kpiComparisonTone('items_per_order', { percent: 8, points: null })).toBe('neutral')
  })

  it('uses the payment cancellation thresholds', () => {
    expect(cancellationTone(4.9)).toBe('positive')
    expect(cancellationTone(5)).toBe('warning')
    expect(cancellationTone(10)).toBe('warning')
    expect(cancellationTone(10.1)).toBe('negative')
  })

  it('colours product deltas by direction', () => {
    expect(deltaTone(3)).toBe('positive')
    expect(deltaTone(-1)).toBe('negative')
    expect(deltaTone(0)).toBe('neutral')
  })

  it('limits Needs Attention colours to semantic actions', () => {
    expect(attentionTone('ndr_over_sla', 1)).toBe('negative')
    expect(attentionTone('reconciliation_exceptions', 2)).toBe('negative')
    expect(attentionTone('follow_up', 5)).toBe('warning')
    expect(attentionTone('on_hold', 1)).toBe('warning')
    expect(attentionTone('ready_booking', 8)).toBe('warning')
    expect(attentionTone('fresh', 100)).toBe('neutral')
    expect(attentionTone('active_ndr', 20)).toBe('neutral')
    expect(attentionTone('ndr_over_sla', 0)).toBe('neutral')
  })
})
