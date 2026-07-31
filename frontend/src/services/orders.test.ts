import { afterEach, describe, expect, it, vi } from 'vitest'
import { bookShiprocketShipment, cancelCourierShipment, checkShiprocketCouriers, clearReconciliationFilter, getOrderOperations, getOrders, reconciliationDataset, reconciliationFilterLabel, reconcileCourierBooking, refreshShiprocketShipment, selectReconciliationFilter, shiprocketCancellationMessage, shouldRemoveCleanupRecord, verifyShiprocketOnlyCancellation, type OrdersReconciliationSummary, type ReconciliationRecord, type ShiprocketCancellationResult, type ShiprocketCleanupRecord } from './orders'

const response = (pageSize: number, total = 0) => new Response(JSON.stringify({
  items: [],
  page: 1,
  page_size: pageSize,
  total,
  total_pages: Math.max(1, Math.ceil(total / pageSize)),
  counts: { operations: 64, fresh: 64, previous: 12, all: 100, labels_to_print: 4, awaiting_confirmation: 2, printed_today: 7, new_orders: 64, cod: 30, prepaid: 70, high_risk: 5, repeat_customers: 9, cod_collectable: 1000, prepaid_value: 2000, awaiting_order_confirmation: 3, awaiting_address_verification: 4, cod_conversion_pending: 5 },
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

  it('sends all three Engage filters without additional requests', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(20))
    await getOrders({ orderConfirmation: 'pending', addressVerification: 'successful', codToPrepaid: 'disabled' })
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('order_confirmation')).toBe('pending')
    expect(url.searchParams.get('address_verification')).toBe('successful')
    expect(url.searchParams.get('cod_to_prepaid')).toBe('disabled')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it.each([{ page: 1, pageSize: 20 as const }, { page: 2, pageSize: 20 as const }, { page: 1, pageSize: 50 as const }, { page: 1, pageSize: 100 as const }])('keeps full counts independent of page request $page/$pageSize', async query => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(query.pageSize, 64))
    const result = await getOrders(query)
    expect(result.counts.fresh).toBe(64)
    expect(result.counts.new_orders).toBe(64)
  })
})

describe('provider-neutral courier client', () => {
  it('loads operations without expecting a couriers array', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ corrected_address: null, call_logs: [], package_details: null }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await expect(getOrderOperations('1')).resolves.toMatchObject({ corrected_address: null, call_logs: [] })
  })

  it('uses safe empty defaults when courier arrays are omitted', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ provider: 'multi', weight_kg: 0.5 }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const result = await checkShiprocketCouriers('1', { weight_kg: 0.5, courier_payment_mode: 'Prepaid' })
    expect(result.couriers).toEqual([])
    expect(result.provider_warnings).toEqual([])
  })

  it('normalizes numeric IDs on the courier response only', async () => {
    vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ provider: 'multi', provider_warnings: [], couriers: [{ courier_id: 43, courier_name: 'Delhivery Surface' }] }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    const result = await checkShiprocketCouriers('1', { weight_kg: 0.5, courier_payment_mode: 'Prepaid' })
    expect(result.couriers[0].courier_id).toBe('43')
  })

  it('omits operator when current-user identity is unavailable', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ provider: 'shadowfax' }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await bookShiprocketShipment('1', { provider: 'shadowfax', courier_name: 'Shadowfax Direct', courier_id: 'Regular', weight_kg: 0.5 })
    const request = fetchMock.mock.calls[0][1] as RequestInit
    expect(JSON.parse(String(request.body))).toEqual({ provider: 'shadowfax', courier_name: 'Shadowfax Direct', courier_id: 'Regular', weight_kg: 0.5 })
  })

  it.each([
    ['tracking', refreshShiprocketShipment, '/courier/tracking/refresh'],
    ['reconciliation', reconcileCourierBooking, '/courier/reconcile'],
    ['cancellation', cancelCourierShipment, '/courier/cancel'],
  ] as const)('uses the common %s endpoint', async (_name, action, path) => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ provider: 'shadowfax', shipment: null, result: { status: 'cancelled', message: 'ok' } }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await action('1')
    expect(String(fetchMock.mock.calls[0][0])).toContain(path)
    expect(fetchMock.mock.calls).toHaveLength(1)
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

const reconciliationRecord = (orderNumber: string, reason: string | null = null): ReconciliationRecord => ({ order: null, order_id: orderNumber, order_number: orderNumber, created_date: null, customer_name: 'Customer', total_amount: 100, payment_type: 'prepaid', risk: 'Low', status: 'Open', reason, shiprocket_order_id: null, shiprocket_status: null, source: 'os' })
const reconciliationSummary: OrdersReconciliationSummary = {
  operations_queue: 2, fresh_orders: 1, previous_pending: 1, shiprocket_new: 2, present_in_both: 1, cleanup_pending: 1, missing_in_shiprocket: 1,
  in_both: ['2'], only_in_os: [], only_in_shiprocket: [], duplicate_mapping_anomalies: [],
  datasets: {
    operations: [reconciliationRecord('1'), reconciliationRecord('2')],
    shiprocket_new: [reconciliationRecord('2'), reconciliationRecord('3')],
    both: [reconciliationRecord('2')],
    cleanup_pending: [reconciliationRecord('3', 'stale Shiprocket state')],
    missing_in_shiprocket: [reconciliationRecord('1', 'not yet synced to Shiprocket')],
  },
}

describe('reconciliation card filtering', () => {
  it('selects one active card and returns the correct cached dataset', () => {
    const active = selectReconciliationFilter(null, 'missing_in_shiprocket')
    expect(active).toBe('missing_in_shiprocket')
    expect(reconciliationFilterLabel(active)).toBe('Missing in Shiprocket')
    expect(reconciliationDataset(reconciliationSummary, active).map(record => record.order_number)).toEqual(['1'])
    expect(selectReconciliationFilter(active, 'both')).toBe('both')
  })

  it('clears the active reconciliation filter', () => {
    expect(clearReconciliationFilter()).toBeNull()
    expect(reconciliationDataset(reconciliationSummary, clearReconciliationFilter())).toEqual([])
  })

  it('does not make API requests when changing reconciliation cards', () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch')
    for (const filter of ['operations', 'shiprocket_new', 'both', 'cleanup_pending', 'missing_in_shiprocket'] as const) {
      reconciliationDataset(reconciliationSummary, selectReconciliationFilter(null, filter))
    }
    expect(fetchMock).not.toHaveBeenCalled()
  })
})
