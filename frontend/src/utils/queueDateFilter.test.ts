import { describe, expect, it } from 'vitest'
import { dispatchQueueDate, matchesOrderQueueFilters, matchesQueueDate, type QueueDateFilter } from './queueDateFilter'

const now = new Date('2026-08-26T12:00:00+05:30')
const filter = (preset: QueueDateFilter['preset'], start = '', end = ''): QueueDateFilter => ({ preset, start, end })

describe('operations queue date filtering', () => {
  it('supports today, yesterday, last seven days, custom and all dates', () => {
    expect(matchesQueueDate('2026-08-26T08:00:00+05:30', filter('today'), now)).toBe(true)
    expect(matchesQueueDate('2026-08-25T23:00:00+05:30', filter('today'), now)).toBe(false)
    expect(matchesQueueDate('2026-08-25T10:00:00+05:30', filter('yesterday'), now)).toBe(true)
    expect(matchesQueueDate('2026-08-20T10:00:00+05:30', filter('last_7_days'), now)).toBe(true)
    expect(matchesQueueDate('2026-08-19T10:00:00+05:30', filter('last_7_days'), now)).toBe(false)
    expect(matchesQueueDate('2026-08-22T10:00:00+05:30', filter('custom', '2026-08-21', '2026-08-22'), now)).toBe(true)
    expect(matchesQueueDate(null, filter('all'), now)).toBe(true)
    expect(matchesQueueDate(null, filter('today'), now)).toBe(false)
  })

  it('combines order date, payment and risk without changing queue membership', () => {
    const order = { createdAt: '2026-08-26T08:00:00+05:30', payment: 'COD', risk: 'High' }
    expect(matchesOrderQueueFilters(order, filter('today'), 'COD', 'High', now)).toBe(true)
    expect(matchesOrderQueueFilters(order, filter('today'), 'Prepaid', 'High', now)).toBe(false)
    expect(matchesOrderQueueFilters(order, filter('today'), 'COD', 'Low', now)).toBe(false)
    expect(matchesOrderQueueFilters(order, filter('yesterday'), 'All', 'All', now)).toBe(false)
  })

  it('uses Shopify creation for Fresh/Previous and canonical dispatch dates for Ready/Manifested', () => {
    const order = { createdAt: '2026-08-26T08:00:00+05:30', payment: 'Prepaid', risk: 'Low' }
    expect(matchesOrderQueueFilters(order, filter('today'), 'All', 'All', now)).toBe(true)
    const shipment = { booked_at: '2026-08-25T10:00:00+05:30', manifested_at: '2026-08-26T10:00:00+05:30' }
    expect(dispatchQueueDate(shipment, 'ready_to_ship')).toBe(shipment.booked_at)
    expect(dispatchQueueDate(shipment, 'manifested')).toBe(shipment.manifested_at)
    expect(matchesQueueDate(dispatchQueueDate(shipment, 'ready_to_ship'), filter('yesterday'), now)).toBe(true)
    expect(matchesQueueDate(dispatchQueueDate(shipment, 'manifested'), filter('today'), now)).toBe(true)
  })
})
