import { afterEach, describe, expect, it, vi } from 'vitest'
import source from './App.tsx?raw'
import { readableApiError, saveAndVerifyOrderAddress } from './services/orders'

afterEach(() => vi.unstubAllGlobals())

describe('Save & Verify address errors', () => {
  it('renders structured validation details instead of object coercion', () => {
    const message = readableApiError({ detail: [{ loc: ['body', 'phone'], msg: 'Field required', type: 'missing' }] }, 'fallback')
    expect(message).toBe('phone: Field required')
    expect(message).not.toContain('[object Object]')
  })

  it('gives a clear stale revision message', () => {
    expect(readableApiError({ detail: 'Address changed in another session (current revision 3). Reload before saving.' }))
      .toBe('Address changed since this drawer was opened. Reload and verify again.')
  })

  it('gives a clear stale token message', () => {
    expect(readableApiError({ detail: 'Address draft identity could not be verified. Reload before saving.' }))
      .toBe('Address verification token expired. Reload the order.')
  })

  it('uses the structured error reader for the Save & Verify transport', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({
      detail: [{ loc: ['body', 'draft_token'], msg: 'Field required', type: 'missing' }],
    }), { status: 422, headers: { 'Content-Type': 'application/json' } })))
    await expect(saveAndVerifyOrderAddress('325270', {})).rejects.toThrow('Address verification token expired. Reload the order.')
  })
})

describe('Save & Verify drawer state propagation', () => {
  const flow = source.slice(source.indexOf('const saveAndVerifyAddress'), source.indexOf('const checkCouriers'))

  it('applies the authoritative operations response and awaits fresh eligibility', () => {
    expect(flow).toContain('setOperations(result.operations)')
    expect(flow).toContain('const freshEligibility = await getBookingEligibility(orderId)')
    expect(flow).toContain('setBookingEligibility(freshEligibility)')
  })

  it('keeps the cross-order generation and order guards intact', () => {
    expect(flow).toContain('canUseDraft(')
    expect(flow).toContain('generation !== drawerGenerationRef.current || selectedOrderId !== orderId')
    expect(flow).toContain('draft_order_id: orderId')
    expect(flow).toContain('expected_revision: operations.address_revision')
    expect(flow).toContain('draft_token: operations.address_draft_token')
  })

  it('exposes explicit ready, saving, verified, and retry states', () => {
    expect(source).toContain("'ready' | 'saving' | 'verified' | 'failed'")
    expect(source).toContain("saving: 'Saving...'")
    expect(source).toContain("verified: 'Verified'")
    expect(source).toContain("failed: 'Failed - retry'")
  })
})
