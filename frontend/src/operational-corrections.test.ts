import { describe, expect, it } from 'vitest'
import { formatDateTime } from './utils/time'
import { ADDRESS_PRIMARY_ACTION, orderContactSectionTitle, showCodCallWorkflow } from './utils/operations'

describe('operational corrections UI', () => {
  it('renders human timestamps in IST with date and time', () => {
    expect(formatDateTime('2026-07-25T06:12:00Z')).toBe('25 Jul 2026, 11:42 AM IST')
  })

  it('renders UTC 13:31 and legacy offset-less UTC as 19:01 IST', () => {
    expect(formatDateTime('2026-08-26T13:31:00Z')).toBe('26 Aug 2026, 07:01 PM IST')
    expect(formatDateTime('2026-08-26T13:31:00')).toBe('26 Aug 2026, 07:01 PM IST')
    expect(formatDateTime('2026-08-26T19:01:00+05:30')).toBe('26 Aug 2026, 07:01 PM IST')
  })

  it('removes the COD workflow for prepaid orders', () => {
    expect(orderContactSectionTitle(true)).toBe('Address Confirmation')
    expect(showCodCallWorkflow(true)).toBe(false)
    expect(orderContactSectionTitle(false)).toBe('COD Call Log')
    expect(showCodCallWorkflow(false)).toBe(true)
  })

  it('timeline timestamps include the required zone suffix', () => {
    expect(formatDateTime('2026-07-25T06:12:00Z')).toContain('11:42 AM IST')
  })

  it('uses the consolidated address action', () => {
    expect(ADDRESS_PRIMARY_ACTION).toBe('Save & Verify Address')
  })
})
