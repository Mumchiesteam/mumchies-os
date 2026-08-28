import { describe, expect, it } from 'vitest'
import { courierSelectionKey, courierSelectionMatches } from './utils/courierSelection'

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

  it('keeps duplicate courier IDs distinct by provider, name and service', () => {
    const first = { provider: 'shiprocket', courier_id: '43', courier_name: 'Delhivery Surface', mode: 'surface' }
    const second = { provider: 'shiprocket', courier_id: '43', courier_name: 'Delhivery Express', mode: 'air' }

    expect(courierSelectionKey(second)).not.toBe(courierSelectionKey(first))
    expect(courierSelectionMatches(second, second)).toBe(true)
    expect(courierSelectionMatches(second, first)).toBe(false)
  })
})
