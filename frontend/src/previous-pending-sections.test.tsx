import { describe, expect, it } from 'vitest'
import { isPreviousPendingToday } from './utils/previousPending'

describe('Previous Pending sections', () => {
  it('uses the durable entry timestamp with an IST day boundary', () => {
    const istMidnight = new Date('2026-09-01T18:30:00.000Z')
    expect(isPreviousPendingToday('2026-09-01T18:29:59.000Z', istMidnight)).toBe(false)
    expect(isPreviousPendingToday('2026-09-01T18:30:00.000Z', istMidnight)).toBe(true)
    expect(isPreviousPendingToday(null, istMidnight)).toBe(false)
  })
})
