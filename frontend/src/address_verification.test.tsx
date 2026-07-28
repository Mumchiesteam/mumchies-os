import { describe, expect, it } from 'vitest'
import { listStatus } from './utils/orderStatus'
import { mapApiOrder, type Order } from './services/orders'

describe('Address Verification & Order Status', () => {
  it('1. Verification with no warnings: status becomes Ready for Booking', () => {
    const order: Partial<Order> = {
      payment: 'Prepaid',
      addressVerified: true,
      addressVerificationStatus: 'verified',
      operationalStatus: 'Address Verification Pending',
      tags: [],
    }
    expect(listStatus(order as Order)).toBe('Ready for Booking')
  })

  it('2. Verification with advisory warning such as missing landmark: status still becomes Ready for Booking', () => {
    const order: Partial<Order> = {
      payment: 'Prepaid',
      addressVerified: true,
      addressVerificationStatus: 'verified',
      operationalStatus: 'Address Verification Pending',
      tags: [],
      correctedAddress: {
        customer_name: 'Test Customer',
        phone: '9999999999',
        address_line1: '123 Main St',
        address_line2: '',
        landmark: '',
        city: 'Mumbai',
        state: 'Maharashtra',
        pincode: '400001',
      },
    }
    expect(listStatus(order as Order)).toBe('Ready for Booking')
  })

  it('3. Address genuinely pending: status remains Address Verification Pending', () => {
    const order: Partial<Order> = {
      payment: 'Prepaid',
      addressVerified: false,
      addressVerificationStatus: 'pending',
      operationalStatus: 'Address Verification Pending',
      tags: [],
    }
    expect(listStatus(order as Order)).toBe('Address Verification Pending')
  })

  it('4. Maps api order containing address_verification_status correctly', () => {
    const apiOrder = {
      order_id: 'ord_123',
      order_number: '323522',
      shopify_name: '#323522',
      created_date: '2026-07-28T00:00:00Z',
      customer_name: 'Jane Doe',
      customer_id: 'cust_1',
      customer_orders_count: 1,
      phone: '9999999999',
      email: 'jane@example.com',
      shipping_address: null,
      products: [],
      total_amount: 531,
      order_total: 531,
      paid_amount: 531,
      outstanding_amount: 0,
      cod_collectable_amount: 0,
      payment_type: 'prepaid',
      payment_status: 'paid',
      fulfillment_status: null,
      shopify_status: null,
      cancelled_at: null,
      tags: [],
      first_action_at: null,
      human_action_count: 1,
      call_attempt_count: 0,
      latest_call_result: null,
      operational_status: 'Ready for Booking',
      address_verified: true,
      address_verification_status: 'verified',
      address_verified_at: '2026-07-28T12:00:00Z',
      address_verified_by: 'operator',
      verified_address_snapshot: null,
      corrected_address: null,
      courier_sync_status: null,
      courier_sync_error: null,
      address_sync_results: null,
      package_details: null,
      selected_courier: null,
      shipment: null,
      external_tracking: null,
    }
    const mapped = mapApiOrder(apiOrder as unknown as Parameters<typeof mapApiOrder>[0])
    expect(mapped.addressVerified).toBe(true)
    expect(mapped.addressVerificationStatus).toBe('verified')
    expect(listStatus(mapped)).toBe('Ready for Booking')
  })
})
