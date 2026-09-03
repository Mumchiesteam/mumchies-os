import { afterEach, describe, expect, it, vi } from 'vitest'
import { canTestShadowfaxCreate, testShadowfaxCreateOrder, type ShadowfaxHealth } from './shadowfax-diagnostic'
import type { Order } from './orders'

afterEach(() => vi.restoreAllMocks())

const health: ShadowfaxHealth = { configured: true, authenticated: true, serviceability_available: true }
const order = (overrides: Partial<Order> = {}): Order => ({
  internalId: '6902274883662', orderNumber: '326294', shopifyName: null, createdAt: '2026-08-20T00:00:00Z', createdDate: '20 Aug 2026', customerName: 'Test', amount: 1, shippingAmount: null, payment: 'Prepaid', orderTotal: 1, paidAmount: 1, outstandingAmount: 0, codCollectableAmount: 0, paymentType: 'prepaid', financialStatus: 'paid', risk: 'Low', fulfillmentStatus: 'unfulfilled', shopifyStatus: 'open', cancelledAt: null, customerId: null, customerOrdersCount: null, isRepeatCustomer: false, phone: null, email: null, shippingAddress: null, products: [], tags: [], firstActionAt: null, humanActionCount: 0, callAttemptCount: 0, latestCallResult: null, operationalStatus: 'Ready for Booking', addressVerified: true, addressVerifiedAt: null, addressVerifiedBy: null, verifiedAddressSnapshot: null, correctedAddress: null, courierSyncStatus: null, courierSyncError: null, addressSyncResults: null, packageDetails: { weight_kg: 0.5, length_cm: 5, breadth_cm: 5, height_cm: 5 }, selectedCourier: null, shipment: null, externalTracking: null, engageOrderId: null, orderConfirmation: null, orderConfirmationMessage: null, addressConfirmation: null, addressConfirmationMessage: null, codToPrepaid: null, codToPrepaidMessage: null, engageLastSyncedAt: null,
  ...overrides,
})

describe('Shadowfax create-only diagnostic', () => {
  it('is visible only for an eligible admin or owner', () => {
    expect(canTestShadowfaxCreate(order(), health, 'admin')).toBe(true)
    expect(canTestShadowfaxCreate(order(), health, 'operator')).toBe(false)
    expect(canTestShadowfaxCreate(order({ fulfillmentStatus: 'fulfilled' }), health, 'owner')).toBe(false)
    expect(canTestShadowfaxCreate(order({ externalTracking: { provider: 'Shadowfax', awb: 'AWB', status: null, trackingUrl: null } }), health, 'owner')).toBe(false)
    expect(canTestShadowfaxCreate(order({ packageDetails: null }), health, 'owner')).toBe(false)
    expect(canTestShadowfaxCreate(order(), { ...health, serviceability_available: false }, 'owner')).toBe(false)
  })

  it('calls exactly the create-only endpoint once', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ outcome: 'success', http_status: 200, message: 'created', validation_errors: null, data: { id: 'SFX-1', awb_number: 'AWB-1' }, payload: {} }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await testShadowfaxCreateOrder('6902274883662')
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/shadowfax/test-create-order/6902274883662')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ method: 'POST' })
  })
})
