import { afterEach, describe, expect, it, vi } from 'vitest'
import { getOrders, shiprocketCancellationMessage, shouldRemoveCleanupRecord, verifyShiprocketOnlyCancellation, type ShiprocketCancellationResult, type ShiprocketCleanupRecord } from './orders'

const response = (pageSize: number, total = 0) => new Response(JSON.stringify({
  items: [],
  page: 1,
  page_size: pageSize,
  total,
  total_pages: Math.max(1, Math.ceil(total / pageSize)),
  counts: { operations: 64, fresh: 64, previous: 12, all: 100, labels_to_print: 4, awaiting_confirmation: 2, printed_today: 7, new_orders: 64, pending_booking: 8, cod: 30, prepaid: 70, high_risk: 5, repeat_customers: 9, cod_collectable: 1000, prepaid_value: 2000 },
}), { status: 200, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.restoreAllMocks())

describe('orders pagination client', () => {
  it('requests the default 20-row first page and preserves totals', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(20, 41))
    const result = await getOrders()
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('page')).toBe('1')
    expect(url.searchParams.get('page_size')).toBe('20')
    expect(result).toMatchObject({ page: 1, pageSize: 20, total: 41, totalPages: 3 })
  })

  it.each([50, 100] as const)('requests %i rows per page', async pageSize => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(pageSize))
    await getOrders({ page: 2, pageSize })
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('page_size')).toBe(String(pageSize))
  })

  it('sends Printed Today as a clickable queue selection', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(20))
    await getOrders({ queue: 'printed_today', page: 1 })
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('queue')).toBe('printed_today')
  })

  it.each([{ page: 1, pageSize: 20 as const }, { page: 2, pageSize: 20 as const }, { page: 1, pageSize: 50 as const }, { page: 1, pageSize: 100 as const }])('keeps full counts independent of page request $page/$pageSize', async query => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(query.pageSize, 64))
    const result = await getOrders(query)
    expect(result.counts.fresh).toBe(64)
    expect(result.counts.new_orders).toBe(64)
    expect(result.counts.pending_booking).toBe(8)
  })
})

const cleanupRecord: ShiprocketCleanupRecord = { order_id: '6813934747726', order_number: '322835', shopify_status: 'Cancelled', mumchies_provider: null, mumchies_status: 'Cancelled', shiprocket_order_id: '1468752948', shiprocket_status: 'NEW', reason: 'Cancelled in Shopify', shiprocket_awb: null }
const cancellationResult = (status: ShiprocketCancellationResult['status']): ShiprocketCancellationResult => ({ status, shiprocket_order_id: '1468752948', channel_order_id: '322835', request_http_status: 200, request_response: {}, verified_top_level_status: 'NEW', verified_top_level_status_code: 1, still_in_new_queue: true, message: '' })

describe('Shiprocket cancellation verification client', () => {
  it('does not display success or remove cleanup rows for inconsistent/unverified results', () => {
    expect(shiprocketCancellationMessage(cancellationResult('inconsistent'))).toContain('still shows as NEW')
    expect(shiprocketCancellationMessage(cancellationResult('unverified'))).toContain('could not be verified')
    expect(shouldRemoveCleanupRecord(cancellationResult('inconsistent'))).toBe(false)
    expect(shouldRemoveCleanupRecord(cancellationResult('unverified'))).toBe(false)
    expect(shouldRemoveCleanupRecord(cancellationResult('confirmed'))).toBe(true)
  })

  it('uses the verification endpoint without sending another cancellation request', async () => {
    const result = cancellationResult('inconsistent')
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify(result), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await verifyShiprocketOnlyCancellation(cleanupRecord)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/shiprocket-only-cancel/verify')
    expect(fetchMock.mock.calls).toHaveLength(1)
  })
})
