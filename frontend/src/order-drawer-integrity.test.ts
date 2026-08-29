import { describe, expect, it } from 'vitest'
import { canUseDraft, emptyAddressDraft, isCurrentCourierSession, isCurrentDrawerQuote, isCurrentDrawerRequest } from './order-drawer-integrity'

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
  it('keeps one sequential drawer session across A eligible, B eligible, C blocked, and D eligible', () => {
    let current = { orderId: 'A', generation: 1, contextKey: 'A-1', requestId: 1, eligible: true, selected: false }
    const select = (identity: typeof current) => {
      if (!isCurrentCourierSession(current, identity) || !current.eligible || current.selected) return 0
      current = { ...current, selected: true }
      return 1
    }
    expect(select({ ...current })).toBe(1)
    current = { orderId: 'B', generation: 2, contextKey: 'B-2', requestId: 1, eligible: true, selected: false }
    expect(select({ ...current })).toBe(1)
    expect(isCurrentCourierSession({ orderId: 'A', generation: 1, contextKey: 'A-1', requestId: 1 }, current)).toBe(false)
    current = { orderId: 'C', generation: 3, contextKey: 'C-3', requestId: 1, eligible: false, selected: false }
    expect(select({ ...current })).toBe(0)
    current = { orderId: 'D', generation: 4, contextKey: 'D-4', requestId: 1, eligible: true, selected: false }
    expect(select({ ...current })).toBe(1)
  })
  it('rejects delayed quote and selection responses after a switch or refresh request', () => {
    const active = { orderId: 'B', generation: 2, contextKey: 'B-2', requestId: 3 }
    expect(isCurrentCourierSession({ orderId: 'A', generation: 1, contextKey: 'A-1', requestId: 1 }, active)).toBe(false)
    expect(isCurrentCourierSession({ ...active, requestId: 2 }, active)).toBe(false)
    expect(isCurrentCourierSession({ ...active }, active)).toBe(true)
  })
  it('rejects a hung refresh response after its timeout settles the same-context session', () => {
    const timedOutSession = { orderId: 'B', generation: 2, contextKey: 'B-2', requestId: 8 }
    const hungRefreshOwner = { ...timedOutSession, requestId: 7 }
    expect(isCurrentCourierSession(hungRefreshOwner, timedOutSession)).toBe(false)
    expect(isCurrentCourierSession({ ...timedOutSession }, timedOutSession)).toBe(true)
  })
})
