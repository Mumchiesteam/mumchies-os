import { describe, expect, it } from 'vitest'
import { canUseDraft, emptyAddressDraft, isCurrentDrawerQuote, isCurrentDrawerRequest } from './order-drawer-integrity'
import { quoteSelectionGate } from './utils/quoteContext'

describe('cross-order drawer integrity', () => {
  it('discards delayed A after switching to B', () => expect(isCurrentDrawerRequest({ orderId: 'A', generation: 1 }, 'B', 2)).toBe(false))
  it('keeps only C after rapid A-B-C switching', () => {
    expect(isCurrentDrawerRequest({ orderId: 'A', generation: 1 }, 'C', 3)).toBe(false)
    expect(isCurrentDrawerRequest({ orderId: 'B', generation: 2 }, 'C', 3)).toBe(false)
    expect(isCurrentDrawerRequest({ orderId: 'C', generation: 3 }, 'C', 3)).toBe(true)
  })
  it('blocks save while initializing or for an old generation', () => {
    expect(canUseDraft({ orderId: 'B', generation: 2 }, 'B', 2, true)).toBe(false)
    expect(canUseDraft({ orderId: 'A', generation: 1 }, 'B', 2, false)).toBe(false)
    expect(canUseDraft({ orderId: 'B', generation: 2 }, 'B', 2, false)).toBe(true)
  })
  it('clears every address field on order switch', () => expect(Object.values(emptyAddressDraft()).every(value => value === '')).toBe(true))
  it('accepts quote readiness only from the active order and generation', () => {
    const b = { orderId: 'B', generation: 2, contextKey: 'B-2' }
    expect(isCurrentDrawerQuote({ orderId: 'A', generation: 1, contextKey: 'A-1' }, b)).toBe(false)
    expect(isCurrentDrawerQuote({ ...b }, b)).toBe(true)
  })
  it('enables exactly one B selection after an incomplete A session', () => {
    const b = { orderId: 'B', generation: 2, contextKey: 'B-2' }
    const aReadiness = { orderId: 'A', generation: 1, contextKey: 'A-1', eligible: false }
    const bReadiness = { ...b, eligible: true }
    const active = isCurrentDrawerQuote(aReadiness, b) ? aReadiness : isCurrentDrawerQuote(bReadiness, b) ? bReadiness : null
    const gate = quoteSelectionGate({ eligible: Boolean(active?.eligible), contextMatches: active !== null, addressVerified: true, paymentMode: 'Prepaid', codConfirmed: true })
    let calls = 0
    if (gate.enabled) calls += 1
    expect(gate).toEqual({ enabled: true, reason: null })
    expect(calls).toBe(1)
  })
})
