export type RiskLevel = 'High' | 'Medium' | 'Low'

export interface OrderProduct {
  productName: string
  sku: string | null
  quantity: number
  weightGrams: number | null
  price: number
}

export interface AddressSyncResults {
  shopify_order: 'synced' | 'failed' | 'not_applicable'
  shopify_customer: 'synced' | 'failed' | 'not_applicable'
  shiprocket: 'synced' | 'failed' | 'not_applicable'
  delhivery: 'synced' | 'failed' | 'manual_required' | 'not_applicable'
  errors?: Record<string, string>
}

export interface ExternalTracking {
  provider: string | null
  awb: string | null
  status: string | null
  trackingUrl: string | null
}

export interface Order {
  internalId: string
  orderNumber: string
  shopifyName: string | null
  createdAt: string
  createdDate: string
  customerName: string
  amount: number
  shippingAmount: number | null
  payment: 'COD' | 'Prepaid' | 'Partial COD'
  orderTotal: number
  paidAmount: number
  outstandingAmount: number
  codCollectableAmount: number
  paymentType: 'prepaid' | 'cod' | 'partial_cod'
  financialStatus: string | null
  risk: RiskLevel
  fulfillmentStatus: string | null
  shopifyStatus: string | null
  cancelledAt: string | null
  customerId: string | null
  customerOrdersCount: number | null
  phone: string | null
  email: string | null
  shippingAddress: {
    name: string | null
    address: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  products: OrderProduct[]
  tags: string[]
  firstActionAt: string | null
  humanActionCount: number
  callAttemptCount: number
  latestCallResult: string | null
  operationalStatus: string | null
  addressVerified: boolean
  addressVerifiedAt: string | null
  addressVerifiedBy: string | null
  verifiedAddressSnapshot: {
    customer_name: string | null
    phone: string | null
    address_line1: string | null
    address_line2: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  correctedAddress: {
    customer_name: string | null
    phone: string | null
    address_line1: string | null
    address_line2: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  courierSyncStatus: string | null
  courierSyncError: string | null
  addressSyncResults: AddressSyncResults | null
  packageDetails: {
    weight_kg: number | null
    length_cm: number | null
    breadth_cm: number | null
    height_cm: number | null
  } | null
  selectedCourier: {
    provider: string | null
    booking_supported: boolean | null
    rate_note: string | null
    courier_id: string | null
    courier_name: string | null
    rate: number | null
    cod_charge: number | null
    total_estimated_shipping_cost: number | null
    estimated_delivery_days: number | null
    expected_delivery_date: string | null
    rating: number | null
    mode: string | null
  } | null
  shipment: {
    order_id: string | null
    provider: string | null
    provider_order_id: string | null
    shiprocket_order_id: string | null
    shipment_id: string | null
    awb: string | null
    courier_name: string | null
    courier_id: string | null
    booking_status: string | null
    booked_at: string | null
    latest_status: string | null
    last_synced_at: string | null
    tracking_url: string | null
    label_url: string | null
    expected_delivery_date: string | null
    delivered_at: string | null
    address_sync_status: string | null
    address_sync_error: string | null
    package_weight_kg: number | null
    package_length_cm: number | null
    package_breadth_cm: number | null
    package_height_cm: number | null
    selected_courier_id: string | null
    selected_courier_name: string | null
    shopify_fulfillment_id: string | null
    shopify_fulfillment_status: string | null
    shopify_fulfillment_sync_status: 'pending' | 'synced' | 'failed' | 'not_applicable' | null
    shopify_fulfillment_synced_at: string | null
    shopify_fulfillment_sync_error: string | null
    shopify_tracking_number: string | null
    shopify_tracking_url: string | null
    shopify_customer_notified: boolean | null
    label_print_status: 'not_printed' | 'awaiting_confirmation' | 'printed' | null
    label_first_printed_at: string | null
    label_last_printed_at: string | null
    label_last_printed_by: string | null
    label_print_count: number
    last_print_batch_id: string | null
    address_confidence_score: number | null
    address_confidence_category: string | null
  } | null
  externalTracking: ExternalTracking | null
}

interface ApiOrder {
  order_id: string
  order_number: string
  shopify_name: string | null
  created_date: string
  customer_name: string | null
  customer_id: string | null
  customer_orders_count: number | null
  phone: string | null
  email: string | null
  shipping_address: {
    name: string | null
    address: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  products: {
    product_name: string
    sku: string | null
    quantity: number
    weight_grams: number | null
    price: number | string
  }[]
  total_amount: number | string
  order_total: number | string
  paid_amount: number | string
  outstanding_amount: number | string
  cod_collectable_amount: number | string
  payment_type: 'prepaid' | 'cod' | 'partial_cod'
  shipping_amount: number | string | null
  payment_status: string | null
  fulfillment_status: string | null
  shopify_status: string | null
  cancelled_at: string | null
  tags: string[]
  first_action_at: string | null
  human_action_count: number
  call_attempt_count: number
  latest_call_result: string | null
  operational_status: string | null
  address_verified: boolean
  address_verified_at: string | null
  address_verified_by: string | null
  verified_address_snapshot: {
    customer_name: string | null
    phone: string | null
    address_line1: string | null
    address_line2: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  corrected_address: {
    customer_name: string | null
    phone: string | null
    address_line1: string | null
    address_line2: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  courier_sync_status: string | null
  courier_sync_error: string | null
  address_sync_results: AddressSyncResults | null
  package_details: {
    weight_kg: number | null
    length_cm: number | null
    breadth_cm: number | null
    height_cm: number | null
  } | null
  selected_courier: {
    provider: string | null
    booking_supported: boolean | null
    rate_note: string | null
    courier_id: string | null
    courier_name: string | null
    rate: number | null
    cod_charge: number | null
    total_estimated_shipping_cost: number | null
    estimated_delivery_days: number | null
    expected_delivery_date: string | null
    rating: number | null
    mode: string | null
  } | null
  shipment: Order['shipment']
  external_tracking: { provider: string | null; awb: string | null; status: string | null; tracking_url: string | null } | null
}

export interface OrderOperations {
  call_logs: { result: string; timestamp: string; operator: string; comment: string | null }[]
  corrected_address: {
    customer_name: string | null
    phone: string | null
    address_line1: string | null
    address_line2: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  address_verified: boolean
  address_verified_at: string | null
  address_verified_by: string | null
  verified_address_snapshot: {
    customer_name: string | null
    phone: string | null
    address_line1: string | null
    address_line2: string | null
    landmark: string | null
    city: string | null
    state: string | null
    pincode: string | null
  } | null
  courier_sync_status: string | null
  courier_sync_error: string | null
  address_sync_results: AddressSyncResults | null
  package_details: Order['packageDetails']
  selected_courier: Order['selectedCourier']
  shipment: Order['shipment']
}

const apiBase = 'http://127.0.0.1:8000'

const formatDate = (value: string) => new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value))

const toMoney = (value: number) => new Intl.NumberFormat('en-IN', { style: 'currency', currency: 'INR', maximumFractionDigits: 0 }).format(value)

const inferRisk = (tags: string[]) => {
  const tagText = tags.join(' ').toLowerCase()
  if (tagText.includes('high')) return 'High'
  if (tagText.includes('medium')) return 'Medium'
  return 'Low'
}

const inferPayment = (paymentStatus: string | null, paymentType?: string): 'COD' | 'Prepaid' | 'Partial COD' => {
  if (paymentType === 'partial_cod') return 'Partial COD'
  if (paymentType === 'cod') return 'COD'
  if (paymentType === 'prepaid') return 'Prepaid'
  const normalized = (paymentStatus || '').toLowerCase()
  return normalized.includes('pending') || normalized.includes('cod') || normalized.includes('partially') ? 'COD' : 'Prepaid'
}

export async function getOrders(signal?: AbortSignal): Promise<Order[]> {
  const response = await fetch(`${apiBase}/api/v1/orders`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? 'Could not load Shopify orders.')
  }

  const data: ApiOrder[] = await response.json()
  return data.map((item): Order => {
    const shipping = item.shipping_amount == null ? null : Number(item.shipping_amount)
    return {
      internalId: item.order_id,
      orderNumber: item.order_number,
      shopifyName: item.shopify_name,
      createdAt: item.created_date,
      createdDate: formatDate(item.created_date),
      customerName: item.customer_name || 'Guest customer',
      amount: Number(item.total_amount),
      shippingAmount: Number.isFinite(shipping ?? NaN) ? shipping : null,
      payment: inferPayment(item.payment_status, item.payment_type),
      orderTotal: Number(item.order_total ?? item.total_amount),
      paidAmount: Number(item.paid_amount ?? 0),
      outstandingAmount: Number(item.outstanding_amount ?? 0),
      codCollectableAmount: Number(item.cod_collectable_amount ?? 0),
      paymentType: item.payment_type,
      financialStatus: item.payment_status,
      risk: inferRisk(item.tags),
      fulfillmentStatus: item.fulfillment_status,
      shopifyStatus: item.shopify_status,
      cancelledAt: item.cancelled_at,
      customerId: item.customer_id,
      customerOrdersCount: item.customer_orders_count,
      phone: item.phone,
      email: item.email,
      shippingAddress: item.shipping_address,
      products: item.products.map(product => ({
        productName: product.product_name,
        sku: product.sku,
        quantity: product.quantity,
        weightGrams: product.weight_grams,
        price: Number(product.price),
      })),
      tags: item.tags,
      firstActionAt: item.first_action_at,
      humanActionCount: item.human_action_count,
      callAttemptCount: item.call_attempt_count,
      latestCallResult: item.latest_call_result,
      operationalStatus: item.operational_status,
      addressVerified: item.address_verified,
      addressVerifiedAt: item.address_verified_at,
      addressVerifiedBy: item.address_verified_by,
      verifiedAddressSnapshot: item.verified_address_snapshot,
      correctedAddress: item.corrected_address,
      courierSyncStatus: item.courier_sync_status,
      courierSyncError: item.courier_sync_error,
      addressSyncResults: item.address_sync_results,
      packageDetails: item.package_details,
      selectedCourier: item.selected_courier,
      shipment: item.shipment,
      externalTracking: item.external_tracking
        ? { provider: item.external_tracking.provider, awb: item.external_tracking.awb, status: item.external_tracking.status, trackingUrl: item.external_tracking.tracking_url }
        : null,
    }
  })
}

export const formatMoney = toMoney

export async function getOrderOperations(orderId: string): Promise<OrderOperations> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/operations`)
  if (!response.ok) {
    throw new Error('Could not load order operations.')
  }
  return response.json()
}

export async function saveOrderAddress(orderId: string, payload: {
  customer_name: string
  phone: string
  address_line1: string
  address_line2: string
  landmark: string
  city: string
  state: string
  pincode: string
  courier_sync_status?: string | null
  courier_sync_error?: string | null
  update_customer_address?: boolean
  one_time_delivery_address?: boolean
  use_as_default_address?: boolean
}): Promise<OrderOperations> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/address`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('Could not save address.')
  }
  return response.json()
}

export async function addOrderCallLog(orderId: string, payload: { result: string; timestamp?: string; operator: string; comment: string }): Promise<OrderOperations> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/call-logs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('Could not save call log.')
  }
  return response.json()
}

export async function verifyOrderAddress(orderId: string, payload: { operator: string; verified_at?: string; address_snapshot: OrderOperations['verified_address_snapshot'] }): Promise<OrderOperations> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/address/verify`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('Could not verify address.')
  }
  return response.json()
}

export async function saveOrderPackage(orderId: string, payload: {
  weight_kg: number
  length_cm?: number | null
  breadth_cm?: number | null
  height_cm?: number | null
}): Promise<{ provider: string; package_details: OrderOperations['package_details'] }> {
  const response = await fetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/package`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('Could not save package details.')
  }
  return response.json()
}

export async function getBookingEligibility(orderId: string): Promise<{
  provider: string
  eligible: boolean
  missing_requirements: string[]
  operational_status: string | null
  payment_mode: string | null
  shipment_exists: boolean
  shipment_status: string | null
  shipment: Order['shipment']
}> {
  const response = await fetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/eligibility`)
  if (!response.ok) {
    throw new Error('Could not check booking eligibility.')
  }
  return response.json()
}

export async function checkShiprocketCouriers(orderId: string, payload: {
  weight_kg: number
  length_cm?: number | null
  breadth_cm?: number | null
  height_cm?: number | null
  courier_payment_mode: string
}): Promise<{
  provider: string
  pickup_postcode: string
  delivery_postcode: string
  payment_mode: string
  weight_kg: number
  provider_warnings: string[]
  couriers: Array<{
    courier_id: string | null
    courier_name: string
    rate: number
    cod_charge: number | null
    total_estimated_shipping_cost: number
    estimated_delivery_days: number | null
    expected_delivery_date: string | null
    rating: number | null
    cod_supported: boolean
    prepaid_supported: boolean
    mode: string | null
    provider: 'shiprocket' | 'delhivery' | 'shadowfax'
    booking_supported: boolean
    rate_note: string
  }>
}> {
  const response = await fetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/couriers/check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail?.message || body?.detail || 'Could not check couriers.')
  }
  return response.json()
}

export async function selectShiprocketCourier(orderId: string, payload: {
  provider: string
  booking_supported: boolean
  rate_note: string
  courier_id: string
  courier_name: string
  rate: number
  cod_charge: number | null
  total_estimated_shipping_cost: number
  estimated_delivery_days: number | null
  expected_delivery_date: string | null
  rating: number | null
  mode: string | null
}): Promise<{ provider: string; selected_courier: OrderOperations['selected_courier'] }> {
  const response = await fetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/couriers/select`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('Could not select courier.')
  }
  return response.json()
}

export async function bookShiprocketShipment(orderId: string, payload: {
  provider: string
  courier_name: string
  courier_id: string
  weight_kg: number
  length_cm?: number | null
  breadth_cm?: number | null
  height_cm?: number | null
}): Promise<{ provider: string; shipment?: Order['shipment']; existing?: boolean }> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/book`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail?.message || body?.detail || 'Could not book shipment.')
  }
  return response.json()
}

export async function refreshShiprocketShipment(orderId: string): Promise<{ provider: string; shipment: Order['shipment'] }> {
  const response = await fetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/refresh`, { method: 'POST' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail?.message || body?.detail || 'Could not refresh shipment status.')
  }
  return response.json()
}

export async function syncShopifyFulfillment(orderId: string): Promise<{ order_id: string; shipment: Order['shipment'] }> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/shopify-fulfillment/sync`, { method: 'POST' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || 'Could not synchronize Shopify fulfillment.')
  }
  return response.json()
}

export async function downloadShippingLabel(orderId: string): Promise<Blob> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/shipment/label`)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail?.message || body?.detail || 'Shipping label is not yet available.')
  }
  const contentType = response.headers.get('content-type') || ''
  if (!contentType.includes('pdf')) throw new Error('Shipping label is not yet available as a PDF.')
  return response.blob()
}

export function shippingLabelUrl(orderId: string, disposition: 'attachment' | 'inline' = 'attachment'): string {
  return `${apiBase}/api/v1/orders/${orderId}/shipment/label?disposition=${disposition}`
}

export async function validateAddress(orderId: string, payload: Record<string, string>): Promise<{ valid: boolean; status: string; blockers: string[]; warnings: string[]; shiprocket_confidence_score: number | null; shiprocket_confidence_category: string | null; shiprocket_message: string }> {
  const response = await fetch(`${apiBase}/api/v1/orders/${orderId}/address/validate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok) throw new Error('Could not validate address.')
  return response.json()
}

export async function exportOrders(mode: 'current' | 'full', orderIds: string[]): Promise<void> {
  const response = await fetch(`${apiBase}/api/v1/orders/export`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, order_ids: orderIds }) })
  if (!response.ok) throw new Error('Could not export orders.')
  const blob = await response.blob()
  const disposition = response.headers.get('content-disposition') || ''
  const filename = disposition.match(/filename="?([^";]+)"?/)?.[1] || 'mumchies-orders.xlsx'
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  URL.revokeObjectURL(url)
}

export async function getLabelQueue(): Promise<{ labels_to_print: NonNullable<Order['shipment']>[]; awaiting_confirmation: NonNullable<Order['shipment']>[]; printed_today: NonNullable<Order['shipment']>[] }> {
  const response = await fetch(`${apiBase}/api/v1/labels/queue`)
  if (!response.ok) throw new Error('Could not load label queue.')
  return response.json()
}

export async function createLabelBatch(orderIds: string[]): Promise<{ id: string; provider: string; status: string; order_ids: string[] }> {
  const response = await fetch(`${apiBase}/api/v1/labels/batches`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_ids: orderIds, operator: 'Amit Kumar' }) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not create label batch.')
  return body
}

export async function confirmLabelBatch(batchId: string, printedOrderIds: string[]): Promise<void> {
  const response = await fetch(`${apiBase}/api/v1/labels/batches/${batchId}/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ printed_order_ids: printedOrderIds, operator: 'Amit Kumar' }) })
  if (!response.ok) throw new Error('Could not confirm label batch.')
}

export const labelBatchPdfUrl = (batchId: string) => `${apiBase}/api/v1/labels/batches/${batchId}/pdf`

export async function getActiveLabelBatches(): Promise<Array<{ id: string; provider: string; status: string; order_ids: string[] }>> {
  const response = await fetch(`${apiBase}/api/v1/labels/batches/active`)
  if (!response.ok) throw new Error('Could not recover pending print batches.')
  return response.json()
}

export async function requestLabelReprint(orderId: string): Promise<void> {
  const response = await fetch(`${apiBase}/api/v1/labels/orders/${orderId}/reprint`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true }) })
  if (!response.ok) throw new Error('Could not return the label to the print queue.')
}
