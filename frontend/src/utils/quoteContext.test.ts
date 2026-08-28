import { describe, expect, it, vi } from 'vitest'
import { quoteAddressesMatch, quoteContextKey, quoteSelectionGate, type QuoteAddress, type QuotePackage } from './quoteContext'

const address: QuoteAddress = { customer_name: 'Customer', phone: '9876543210', address_line1: 'Street', address_line2: '', landmark: '', city: 'Mumbai', state: 'Maharashtra', pincode: '400001' }
const pkg: QuotePackage = { weight_kg: 0.5, length_cm: 10, breadth_cm: 11, height_cm: 12 }
const key = (overrides: Partial<Parameters<typeof quoteContextKey>[0]> = {}) => quoteContextKey({ orderId: '1', generation: 3, address, paymentMode: 'Prepaid', codAmount: 0, package: pkg, ...overrides })

describe('early courier quote context and gates', () => {
  it('keeps prepaid prefetched cards locked until address verification', () => {
    expect(quoteSelectionGate({ eligible: false, contextMatches: true, addressVerified: false, paymentMode: 'Prepaid', codConfirmed: true })).toEqual({ enabled: false, reason: 'Verify address to select' })
    expect(quoteSelectionGate({ eligible: true, contextMatches: true, addressVerified: true, paymentMode: 'Prepaid', codConfirmed: true }).enabled).toBe(true)
  })

  it('keeps COD cards locked until both verification and confirmation', () => {
    expect(quoteSelectionGate({ eligible: false, contextMatches: true, addressVerified: false, paymentMode: 'COD', codConfirmed: false }).reason).toBe('Verify address to select')
    expect(quoteSelectionGate({ eligible: false, contextMatches: true, addressVerified: true, paymentMode: 'COD', codConfirmed: false }).reason).toBe('COD confirmation required')
    expect(quoteSelectionGate({ eligible: true, contextMatches: true, addressVerified: true, paymentMode: 'COD', codConfirmed: true }).enabled).toBe(true)
  })

  it('unlocks an unchanged prefetched context without a second context key', () => {
    expect(key()).toBe(key())
    expect(quoteSelectionGate({ eligible: true, contextMatches: true, addressVerified: true, paymentMode: 'Prepaid', codConfirmed: true }).enabled).toBe(true)
  })

  it('invalidates on changed pincode, dimensions, weight, or drawer generation', () => {
    expect(key({ address: { ...address, pincode: '400002' } })).not.toBe(key())
    expect(key({ package: { ...pkg, length_cm: 20 } })).not.toBe(key())
    expect(key({ package: { ...pkg, weight_kg: 0.75 } })).not.toBe(key())
    expect(key({ generation: 4 })).not.toBe(key())
  })

  it('normalizes partial COD into a COD-sensitive fingerprint', () => {
    expect(key({ paymentMode: 'Partial COD', codAmount: 250 })).toContain('"payment_mode":"COD"')
    expect(key({ paymentMode: 'Partial COD', codAmount: 250 })).not.toBe(key({ paymentMode: 'Partial COD', codAmount: 300 }))
  })

  it('never enables stale cards from a different context', () => {
    expect(quoteSelectionGate({ eligible: true, contextMatches: false, addressVerified: true, paymentMode: 'Prepaid', codConfirmed: true })).toEqual({ enabled: false, reason: 'Refreshing courier options…' })
  })

  it('requires the displayed draft to still match the verified address', () => {
    expect(quoteAddressesMatch(address, address)).toBe(true)
    expect(quoteAddressesMatch({ ...address, pincode: '400002' }, address)).toBe(false)
    expect(quoteAddressesMatch(address, null)).toBe(false)
  })

  it('enables courier selection for a canonical verified address in the current quote context', () => {
    const verified = quoteAddressesMatch(address, address)
    expect(quoteSelectionGate({ eligible: true, contextMatches: true, addressVerified: verified, paymentMode: 'COD', codConfirmed: true })).toEqual({ enabled: true, reason: null })
  })

  it('selects a loaded, ready quote exactly once', () => {
    const onSelect = vi.fn()
    const gate = quoteSelectionGate({ eligible: true, contextMatches: true, addressVerified: quoteAddressesMatch(address, address), paymentMode: 'COD', codConfirmed: true })
    if (gate.enabled) onSelect()
    expect(onSelect).toHaveBeenCalledTimes(1)
  })
})
