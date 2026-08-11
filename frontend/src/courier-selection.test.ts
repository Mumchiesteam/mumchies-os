import { describe, expect, it } from 'vitest'
import { courierSelectionMatches } from './utils/courierSelection'

const quote = { provider: 'shiprocket', courier_id: '43', courier_name: 'Delhivery Surface', mode: 'surface' }

describe('canonical courier selection', () => {
  it('does not enable booking when a refreshed quote has the old ID but persistence was cleared', () => {
    expect(courierSelectionMatches(null, quote)).toBe(false)
  })

  it('requires the persisted provider, courier, name and service to match', () => {
    expect(courierSelectionMatches({ ...quote }, quote)).toBe(true)
    expect(courierSelectionMatches({ ...quote, provider: 'delhivery' }, quote)).toBe(false)
    expect(courierSelectionMatches({ ...quote, courier_id: '44' }, quote)).toBe(false)
    expect(courierSelectionMatches({ ...quote, courier_name: 'Different service' }, quote)).toBe(false)
    expect(courierSelectionMatches({ ...quote, mode: 'air' }, quote)).toBe(false)
  })
})
