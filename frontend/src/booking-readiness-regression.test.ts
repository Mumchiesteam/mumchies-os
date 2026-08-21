import { describe, expect, it } from 'vitest'

import appSource from './App.tsx?raw'

describe('first-attempt booking readiness', () => {
  it('replaces drawer-open eligibility with post-package lookup readiness', () => {
    expect(appSource).toContain('setBookingEligibility(result.booking_readiness)')
    expect(appSource.indexOf('setBookingEligibility(result.booking_readiness)'))
      .toBeLessThan(appSource.indexOf('const sorted = [...(result.couriers ?? [])]'))
  })

  it('does not weaken the booking integrity checks', () => {
    expect(appSource).toContain('!bookingEligibility?.eligible')
    expect(appSource).toContain('getBookingContextPreview')
    expect(appSource).toContain('booking_context_hash: preview.booking_context_hash')
  })
})
