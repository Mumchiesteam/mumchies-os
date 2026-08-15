import { describe, expect, it } from 'vitest'
import { canUseDraft, emptyAddressDraft, isCurrentDrawerRequest } from './order-drawer-integrity'

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
})
