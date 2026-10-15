import { describe, expect, it } from 'vitest'
import source from './App.tsx?raw'

describe('Shadowfax courier comparison', () => {
  it('renders Shadowfax Direct as the selectable option and keeps reconciliation as a fallback', () => {
    expect(source).toContain("option.provider === 'shadowfax' && option.mode === 'Direct'")
    expect(source).toContain('Shadowfax Direct selected')
    expect(source).toContain('Reconcile externally booked Shadowfax shipment')
    expect(source).toContain('{showShadowfaxForm && !shipment')
    expect(source).not.toContain("selectedCourier.mode === 'Direct' ? 'Book with Shadowfax' : 'Reconcile Shadowfax Shipment'")
  })

  it('shows missing prices as unavailable and sorts them after priced quotes', () => {
    expect(source).toContain('Number.POSITIVE_INFINITY')
    expect(source).toContain("rate !== null ? formatMoney(rate) : 'Rate unavailable'")
    expect(source).toContain("totalRate !== null ? formatMoney(totalRate) : 'Rate unavailable'")
  })
})
