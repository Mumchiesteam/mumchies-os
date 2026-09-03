import { afterEach, describe, expect, it, vi } from 'vitest'
import appSource from './App.tsx?raw'
import { testShadowfaxCreateOnly, type Order, type ShadowfaxHealthCheck } from './services/orders'
import { canTestShadowfaxCreate, getShadowfaxCreateTestAvailability } from './utils/shadowfaxCreateDiagnostic'

const healthyShadowfax = { overall: 'PASS' } as ShadowfaxHealthCheck
const order = (overrides: Partial<Order> = {}): Order => ({
  internalId: 'shopify-1', orderNumber: '326446', shopifyName: '#326446', createdAt: '', createdDate: '',
  customerName: 'Customer', amount: 100, shippingAmount: null, payment: 'Prepaid', orderTotal: 100,
  paidAmount: 100, outstandingAmount: 0, codCollectableAmount: 0, paymentType: 'prepaid',
  financialStatus: 'paid', risk: 'Low', fulfillmentStatus: 'unfulfilled', shopifyStatus: 'open', cancelledAt: null,
  customerId: null, customerOrdersCount: null, isRepeatCustomer: false, phone: null, email: null,
  shippingAddress: null, products: [], tags: [], firstActionAt: null, humanActionCount: 0, callAttemptCount: 0,
  latestCallResult: null, operationalStatus: null, addressVerified: true, addressVerifiedAt: null,
  addressVerifiedBy: null, verifiedAddressSnapshot: null, correctedAddress: null, courierSyncStatus: null,
  courierSyncError: null, addressSyncResults: null,
  packageDetails: { weight_kg: 0.5, length_cm: 10, breadth_cm: 8, height_cm: 6 }, selectedCourier: null,
  shipment: null, externalTracking: null, engageOrderId: null, orderConfirmation: null,
  orderConfirmationMessage: null, addressConfirmation: null, addressConfirmationMessage: null,
  codToPrepaid: null, codToPrepaidMessage: null,
  ...overrides,
} as unknown as Order)

afterEach(() => vi.restoreAllMocks())

describe('Shadowfax create-only diagnostic', () => {
  it('is visible only to an admin or owner for an unfulfilled, unshipped order with a package', () => {
    expect(canTestShadowfaxCreate(order(), 'admin', healthyShadowfax)).toBe(true)
    expect(canTestShadowfaxCreate(order(), 'owner', healthyShadowfax)).toBe(true)
    expect(canTestShadowfaxCreate(order(), 'operator', healthyShadowfax)).toBe(false)
    expect(canTestShadowfaxCreate(order({ fulfillmentStatus: 'fulfilled' }), 'admin', healthyShadowfax)).toBe(false)
    expect(canTestShadowfaxCreate(order({ shipment: { awb: 'AWB-1' } as Order['shipment'] }), 'admin', healthyShadowfax)).toBe(false)
    expect(canTestShadowfaxCreate(order({ packageDetails: null }), 'admin', healthyShadowfax)).toBe(false)
    expect(canTestShadowfaxCreate(order(), 'admin', null)).toBe(false)
    expect(canTestShadowfaxCreate(order(), 'admin', { overall: 'FAIL' } as ShadowfaxHealthCheck)).toBe(false)
  })

  it('keeps the admin diagnostic disabled with the exact blocker message', () => {
    const availability = getShadowfaxCreateTestAvailability(order({ shipment: { awb: 'AWB-1' } as Order['shipment'] }), 'admin', healthyShadowfax)

    expect(availability).toEqual({ canCreate: false, blocker: 'Order already has shipment evidence' })
  })

  it('uses the drawer’s Ready for Booking state instead of a stale raw fulfillment field', () => {
    const availability = getShadowfaxCreateTestAvailability(order({ fulfillmentStatus: 'fulfilled', operationalStatus: 'Ready for Booking', shipment: null, externalTracking: null }), 'admin', healthyShadowfax)

    expect(availability).toEqual({ canCreate: true, blocker: null })
    expect(availability.blocker).not.toBe('Order already fulfilled')
  })

  it('calls only the create-only diagnostic endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({
      outcome: 'success', http_status: 201, message: 'Success', validation_errors: null,
      data: { id: 4500, awb_number: 'SF-1' }, payload: {},
    }), { status: 200, headers: { 'Content-Type': 'application/json' } }))

    await testShadowfaxCreateOnly('shopify-1')

    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/shadowfax/test-create-order/shopify-1')
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe('POST')
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('/book')
    expect(fetchMock).toHaveBeenCalledTimes(1)
  })

  it('wires pending, success, and failure feedback without invoking normal booking', () => {
    expect(appSource).toContain("shadowfaxCreateTesting ? 'Testing Shadowfax...' : 'Test Shadowfax Create'")
    expect(appSource).toContain('disabled={!shadowfaxCreateTestAvailability.canCreate || shadowfaxCreateTesting || Boolean(shadowfaxCreateResult)}')
    expect(appSource).toContain('shadowfaxCreateTestAvailability.blocker')
    for (const label of ['Outcome:', 'HTTP status:', 'Validation errors:', 'Shadowfax order ID:', 'AWB number:', 'Payload:', 'Shadowfax order created. Do not test again.']) {
      expect(appSource).toContain(label)
    }
    const handlerStart = appSource.indexOf('const testShadowfaxCreate = async')
    const handler = appSource.slice(handlerStart, appSource.indexOf('\n  const ', handlerStart + 20))
    expect(handler).toContain('testShadowfaxCreateOnly(selectedOrder.internalId)')
    expect(handler).not.toContain('bookShiprocketShipment')
  })
})
