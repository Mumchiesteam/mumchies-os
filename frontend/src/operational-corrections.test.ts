import { describe, expect, it } from 'vitest'
import { formatDateTime } from './utils/time'
import { ADDRESS_PRIMARY_ACTION, orderContactSectionTitle, showCodCallWorkflow } from './utils/operations'

describe('operational corrections UI', () => {
  it('renders human timestamps in IST with date and time', () => {
    expect(formatDateTime('2026-07-25T06:12:00Z')).toBe('25 Jul 2026, 11:42 AM IST')
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
