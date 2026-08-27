import { describe, expect, it } from 'vitest'
import { AbortableRequestGate } from './requestGate'

describe('AbortableRequestGate', () => {
  it('aborts stale requests and only keeps the newest request current', () => {
    const gate = new AbortableRequestGate()

    const first = gate.start()
    const second = gate.start()

    expect(first.signal.aborted).toBe(true)
    expect(first.isCurrent()).toBe(false)
    expect(second.signal.aborted).toBe(false)
    expect(second.isCurrent()).toBe(true)

    gate.invalidate()

    expect(second.signal.aborted).toBe(true)
    expect(second.isCurrent()).toBe(false)
  })
})
