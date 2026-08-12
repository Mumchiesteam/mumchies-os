import { getCsrfToken } from './auth-state'

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
    phone: string | null
    address: string | null
    addressLine1: string | null
    addressLine2: string | null
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
    booking_mode: string | null
    booking_freight: number | null
    booking_operator: string | null
    booking_note: string | null
    booked_at: string | null
    latest_status: string | null
    normalized_status: string | null
    courier_service: string | null
    latest_tracking_at: string | null
    latest_scan: string | null
    terminal_status: string | null
    last_synced_at: string | null
    tracking_url: string | null
    label_url: string | null
    label_format: 'pdf' | 'png' | 'jpeg' | null
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
    dispatch_status: 'ready_to_ship' | 'manifested' | null
    manifested_at: string | null
    manifested_by: string | null
    label_first_printed_at: string | null
    label_last_printed_at: string | null
    label_last_printed_by: string | null
    label_print_count: number
    last_print_batch_id: string | null
    raw_provider_response: string | null
    booking_confidence: 'confirmed' | 'uncertain' | 'reconciled' | null
    reconciliation_status: 'not_required' | 'pending' | 'confirmed' | 'failed' | 'manual_review' | null
    reconciliation_error: string | null
    evidence_source?: 'internal_and_shopify' | 'shopify_fulfillment' | null
    readback_reconciliation_status?: 'reconciled' | 'unavailable' | null
    readback_reconciliation_error?: string | null
    ndr_reason: string | null
    ndr_attempt: number | null
    ndr_remarks: string | null
    ndr_operator_action: string | null
    address_confidence_score: number | null
    address_confidence_category: string | null
  } | null
  externalTracking: ExternalTracking | null
  engageOrderId: string | null
  orderConfirmation: unknown
  orderConfirmationMessage: string | null
  addressConfirmation: unknown
  addressConfirmationMessage: string | null
  codToPrepaid: unknown
  codToPrepaidMessage: string | null
  engageLastSyncedAt: string | null
  customerCancellationRequested?: boolean
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
    phone: string | null
    address: string | null
    address_line1: string | null
    address_line2: string | null
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
  engage_order_id: string | null
  order_confirmation: unknown
  order_confirmation_message: string | null
  address_confirmation: unknown
  address_confirmation_message: string | null
  cod_to_prepaid: unknown
  cod_to_prepaid_message: string | null
  engage_last_synced_at: string | null
  customer_cancellation_requested: boolean
}

export interface OrderOperations {
  call_logs: { result: string; timestamp: string; operator: string; comment: string | null }[]
  address_confirmation_comments: { comment: string; timestamp: string; operator: string }[]
  human_actions?: { action: string; timestamp: string; operator: string | null }[]
  timeline_events?: { action: string; timestamp: string; operator: string | null; details: Record<string, unknown> }[]
  cancellation?: Record<string, unknown> | null
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

export const apiBase = (import.meta.env.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

export const apiFetch = async (input: RequestInfo | URL, init: RequestInit = {}) => {
  const method = (init.method || 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (!['GET', 'HEAD'].includes(method)) headers.set('X-CSRF-Token', getCsrfToken())
  const response = await fetch(input, { ...init, headers, credentials: 'include' })
  if (response.status === 401) window.dispatchEvent(new Event('mumchies:unauthorised'))
  return response
}

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

export interface OrdersPage {
  items: Order[]
  page: number
  pageSize: number
  total: number
  totalPages: number
  counts: OrderCounts
}

export interface OrderCounts {
  operations: number
  fresh: number
  previous: number
  follow_up: number
  on_hold: number
  all: number
  ready_to_ship: number
  manifested: number
  new_orders: number
  cod: number
  prepaid: number
  high_risk: number
  repeat_customers: number
  cod_collectable: number
  prepaid_value: number
  awaiting_order_confirmation: number
  awaiting_address_verification: number
  cod_conversion_pending: number
}

export interface OrdersQuery {
  page?: number
  pageSize?: 20 | 50 | 100
  queue?: 'fresh' | 'previous' | 'all' | 'printed_today'
  search?: string
  payment?: string
  risk?: string
  sort?: string
  orderConfirmation?: string
  addressVerification?: string
  codToPrepaid?: string
  attempt?: 'all' | '1' | '2' | '3' | '4_plus'
  pendingView?: 'follow_up' | 'on_hold'
}

export const mapApiOrder = (item: ApiOrder): Order => {
  const shipping = item.shipping_amount == null ? null : Number(item.shipping_amount)
  return {
    internalId: item.order_id, orderNumber: item.order_number, shopifyName: item.shopify_name,
    createdAt: item.created_date, createdDate: formatDate(item.created_date), customerName: item.customer_name || 'Guest customer',
    amount: Number(item.total_amount), shippingAmount: Number.isFinite(shipping ?? NaN) ? shipping : null,
    payment: inferPayment(item.payment_status, item.payment_type), orderTotal: Number(item.order_total ?? item.total_amount),
    paidAmount: Number(item.paid_amount ?? 0), outstandingAmount: Number(item.outstanding_amount ?? 0), codCollectableAmount: Number(item.cod_collectable_amount ?? 0),
    paymentType: item.payment_type, financialStatus: item.payment_status, risk: inferRisk(item.tags), fulfillmentStatus: item.fulfillment_status,
    shopifyStatus: item.shopify_status, cancelledAt: item.cancelled_at, customerId: item.customer_id, customerOrdersCount: item.customer_orders_count,
    phone: item.phone, email: item.email, shippingAddress: item.shipping_address ? {
      name: item.shipping_address.name,
      phone: item.shipping_address.phone,
      address: item.shipping_address.address,
      addressLine1: item.shipping_address.address_line1,
      addressLine2: item.shipping_address.address_line2,
      landmark: item.shipping_address.landmark,
      city: item.shipping_address.city,
      state: item.shipping_address.state,
      pincode: item.shipping_address.pincode,
    } : null,
    products: item.products.map(product => ({ productName: product.product_name, sku: product.sku, quantity: product.quantity, weightGrams: product.weight_grams, price: Number(product.price) })),
    tags: item.tags, firstActionAt: item.first_action_at, humanActionCount: item.human_action_count, callAttemptCount: item.call_attempt_count,
    latestCallResult: item.latest_call_result, operationalStatus: item.operational_status, addressVerified: item.address_verified,
    addressVerifiedAt: item.address_verified_at, addressVerifiedBy: item.address_verified_by, verifiedAddressSnapshot: item.verified_address_snapshot,
    correctedAddress: item.corrected_address, courierSyncStatus: item.courier_sync_status, courierSyncError: item.courier_sync_error,
    addressSyncResults: item.address_sync_results, packageDetails: item.package_details, selectedCourier: item.selected_courier, shipment: item.shipment,
    externalTracking: item.external_tracking ? { provider: item.external_tracking.provider, awb: item.external_tracking.awb, status: item.external_tracking.status, trackingUrl: item.external_tracking.tracking_url } : null,
    engageOrderId: item.engage_order_id, orderConfirmation: item.order_confirmation, orderConfirmationMessage: item.order_confirmation_message,
    addressConfirmation: item.address_confirmation, addressConfirmationMessage: item.address_confirmation_message,
    codToPrepaid: item.cod_to_prepaid, codToPrepaidMessage: item.cod_to_prepaid_message, engageLastSyncedAt: item.engage_last_synced_at,
    customerCancellationRequested: item.customer_cancellation_requested,
  }
}

export async function getOrders(query: OrdersQuery = {}, signal?: AbortSignal): Promise<OrdersPage> {
  const params = new URLSearchParams({
    page: String(query.page ?? 1),
    page_size: String(query.pageSize ?? 20),
    queue: query.queue ?? 'all',
    search: query.search ?? '',
    payment: query.payment ?? 'all',
    risk: query.risk ?? 'all',
    sort: query.sort ?? 'newest',
    order_confirmation: query.orderConfirmation ?? 'all',
    address_verification: query.addressVerification ?? 'all',
    cod_to_prepaid: query.codToPrepaid ?? 'all',
    attempt: query.attempt ?? 'all',
    pending_view: query.pendingView ?? 'follow_up',
  })
  const response = await apiFetch(`${apiBase}/api/v1/orders?${params}`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? 'Could not load Shopify orders.')
  }

  const data: { items: ApiOrder[]; page: number; page_size: number; total: number; total_pages: number; counts: OrderCounts } = await response.json()
  const items = data.items.map(mapApiOrder)
  return { items, page: data.page, pageSize: data.page_size, total: data.total, totalPages: data.total_pages, counts: data.counts }
}

export interface ShiprocketCleanupRecord {
  order_id: string
  order_number: string
  shopify_status: string
  mumchies_provider: string | null
  mumchies_status: string | null
  shiprocket_order_id: string
  shiprocket_status: string
  reason: string
  shiprocket_awb: null
  last_verification?: ShiprocketCancellationResult | null
}

export interface ShiprocketCancellationResult {
  status: 'confirmed' | 'rejected' | 'inconsistent' | 'unverified'
  shiprocket_order_id: string
  channel_order_id: string
  request_http_status: number | null
  request_response: unknown
  verified_top_level_status: string | null
  verified_top_level_status_code: number | null
  still_in_new_queue: boolean | null
  message: string
}

export interface OrdersReconciliationSummary {
  last_refreshed_at?: string | null
  refresh_error?: string | null
  refreshing?: boolean
  operations_queue: number
  fresh_orders: number
  previous_pending: number
  shiprocket_new: number
  present_in_both: number
  cleanup_pending: number
  missing_in_shiprocket: number
  in_both: string[]
  only_in_os: { order_number: string; reason: string; shiprocket_status: string | null }[]
  only_in_shiprocket: { order_number: string; reason: string; shiprocket_status: string | null }[]
  duplicate_mapping_anomalies: { order_number: string; os_records: number; shiprocket_records: number }[]
  datasets: Record<ReconciliationFilter, ReconciliationRecord[]>
}

export type ReconciliationFilter = 'operations' | 'shiprocket_new' | 'both' | 'cleanup_pending' | 'missing_in_shiprocket'

export interface ReconciliationRecord {
  order: ApiOrder | null
  order_id: string
  order_number: string
  created_date: string | null
  customer_name: string | null
  total_amount: number
  payment_type: string
  risk: string
  status: string
  reason: string | null
  shiprocket_order_id: string | null
  shiprocket_status: string | null
  source: 'os' | 'shiprocket' | 'both'
}

export const reconciliationFilterLabel = (filter: ReconciliationFilter) => ({
  operations: 'Operations Queue',
  shiprocket_new: 'Shiprocket New',
  both: 'Present in Both',
  cleanup_pending: 'Cleanup Pending',
  missing_in_shiprocket: 'Missing in Shiprocket',
}[filter])

export const selectReconciliationFilter = (_current: ReconciliationFilter | null, next: ReconciliationFilter): ReconciliationFilter => next
export const clearReconciliationFilter = (): null => null
export const reconciliationDataset = (summary: OrdersReconciliationSummary | null, filter: ReconciliationFilter | null): ReconciliationRecord[] => filter && summary ? summary.datasets[filter] || [] : []

export async function getOrdersReconciliation(refresh = false): Promise<OrdersReconciliationSummary> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/reconciliation-summary${refresh ? '?refresh=true' : ''}`)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(typeof body?.detail === 'string' ? body.detail : 'Could not reconcile Mumchies OS and Shiprocket.')
  }
  return response.json()
}

export async function getShiprocketCleanupPending(): Promise<{ items: ShiprocketCleanupRecord[]; total: number }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/shiprocket-cleanup-pending`)
  if (!response.ok) throw new Error('Could not reconcile Shiprocket New orders.')
  return response.json()
}

export async function cancelShiprocketOnly(record: ShiprocketCleanupRecord): Promise<ShiprocketCancellationResult> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${record.order_id}/shiprocket-only-cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ shiprocket_order_id: record.shiprocket_order_id, order_number: record.order_number }) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not safely cancel the Shiprocket order.')
  return body
}

export async function verifyShiprocketOnlyCancellation(record: ShiprocketCleanupRecord): Promise<ShiprocketCancellationResult> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${record.order_id}/shiprocket-only-cancel/verify`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ shiprocket_order_id: record.shiprocket_order_id, order_number: record.order_number }) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not verify the Shiprocket cancellation.')
  return body
}

export const shiprocketCancellationMessage = (result: ShiprocketCancellationResult) => ({
  confirmed: 'Shiprocket order cancelled successfully.',
  inconsistent: 'Shiprocket recorded cancellation activity, but the order still shows as NEW. Please review it in Shiprocket.',
  rejected: 'Shiprocket rejected the cancellation.',
  unverified: 'Cancellation request was sent, but the final Shiprocket status could not be verified.',
}[result.status])

export const shouldRemoveCleanupRecord = (result: ShiprocketCancellationResult) => result.status === 'confirmed'

export const formatMoney = toMoney

export async function getOrderOperations(orderId: string): Promise<OrderOperations> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/operations`)
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
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/address`, {
    method: 'PUT',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('Could not save address.')
  }
  return response.json()
}

export async function addOrderCallLog(orderId: string, payload: { result: string; timestamp?: string; comment: string }): Promise<OrderOperations> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/call-logs`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    throw new Error('Could not save call log.')
  }
  return response.json()
}

export async function recordCodWhatsAppOpened(orderId: string): Promise<OrderOperations> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/whatsapp/cod-confirmation-opened`, { method: 'POST' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not save WhatsApp audit event.')
  return body
}

export async function saveManualShadowfaxShipment(orderId: string, payload: { awb?: string; provider_id?: string; service_name?: string; booked_at?: string; freight?: number; note?: string }): Promise<{ provider: string; shipment: Order['shipment']; warning?: string; shiprocket_cleanup?: { status: string; error?: string } }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/shadowfax/manual`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not save manual Shadowfax shipment.')
  return body
}

export async function testShadowfaxDirect324663(): Promise<{ booking: { provider_order_id?: string; awb?: string; status?: string }; tracking: { status?: string } }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/shadowfax-test-324663`, { method: 'POST' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail?.message || body?.detail || 'Shadowfax direct test failed.')
  return body
}

export type ShadowfaxDirectTestState = Record<string, unknown>
export type ShadowfaxShipmentRowDiagnostic = {
  order_number: '324663'
  shopify_order_id: string
  row_exists: boolean
  fields: Record<string, unknown>
  non_null: Record<string, boolean>
  reset_blocker: { evaluates_true: boolean; condition: string; true_fields: string[] }
}

export async function getShadowfaxDirect324663Status(): Promise<ShadowfaxDirectTestState> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/shadowfax-test-324663/status`)
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not load Shadowfax test status.')
  return body.state || {}
}

export async function getShadowfaxShipmentRow324663(): Promise<ShadowfaxShipmentRowDiagnostic> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/shadowfax-test-324663/shipment-row`)
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not load the canonical shipment row.')
  return body
}

export async function repairShadowfaxStaleState324541(): Promise<{ provider_order_id_cleared: boolean; test_state_reset: boolean; state: ShadowfaxDirectTestState }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/shadowfax-test-324541/repair-stale-state`, { method: 'POST' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not repair the stale Shadowfax test state.')
  return body
}

export async function resetShadowfaxDirect324541(): Promise<ShadowfaxDirectTestState> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/shadowfax-test-324541/reset`, { method: 'POST' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not reset the Shadowfax test.')
  return body.state || {}
}

export async function addAddressConfirmationComment(orderId: string, comment: string): Promise<OrderOperations> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/address-confirmation-comments`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment }) })
  if (!response.ok) throw new Error('Could not save address confirmation comment.')
  return response.json()
}

export async function saveAndVerifyOrderAddress(orderId: string, payload: Record<string, string | null>): Promise<{ operations: OrderOperations; validation: { status: string; blockers: string[]; warnings: string[]; shiprocket_message: string }; verified: boolean }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/address/save-verify`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not save and verify address.')
  return body
}

export type CancellationPreflight = { allowed: boolean; blocked_reason: string | null; shopify: { exists: boolean; cancelled: boolean; fulfillment_status: string | null }; shiprocket: { exists: boolean; order_id: string | null; status: string | null; awb: string | null; lookup_error: string | null }; shipment: { exists: boolean; provider: string | null; awb: string | null; status: string | null } }
export async function getCancellationPreflight(orderId: string): Promise<CancellationPreflight> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/cancellation/preflight`)
  if (!response.ok) throw new Error('Could not check cancellation safety.')
  return response.json()
}
export async function cancelOrder(orderId: string, comment: string): Promise<{ results: Record<string, { status: string; error?: string }>; operations: OrderOperations }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ comment, cancel_shopify: true, cancel_shiprocket: true }) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not cancel order.')
  return body
}

export async function retryShiprocketCleanup(orderId: string): Promise<{ status: string; error?: string }> {
  const response = await apiFetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/cleanup-unused`, { method: 'POST' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not retry Shiprocket cleanup.')
  return body
}

export async function verifyOrderAddress(orderId: string, payload: { verified_at?: string; address_snapshot: OrderOperations['verified_address_snapshot'] }): Promise<OrderOperations> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/address/verify`, {
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
  const response = await apiFetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/package`, {
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
  const response = await apiFetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/eligibility`)
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
  const response = await apiFetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/couriers/check`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail?.message || body?.detail || 'Could not check couriers.')
  }
  const result = await response.json()
  const couriers = Array.isArray(result?.couriers) ? result.couriers : []
  return {
    ...result,
    provider_warnings: Array.isArray(result?.provider_warnings) ? result.provider_warnings : [],
    couriers: couriers.map((quote: { courier_id: unknown }) => ({
      ...quote,
      courier_id: quote.courier_id == null ? null : String(quote.courier_id),
    })),
  }
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
  const response = await apiFetch(`${apiBase}/api/v1/couriers/shiprocket/orders/${orderId}/couriers/select`, {
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
}): Promise<{ provider: string; shipment?: Order['shipment']; existing?: boolean; warning?: string; shiprocket_cleanup?: { status: string; error?: string } }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/book`, {
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
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/courier/tracking/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail?.message || body?.detail || 'Could not refresh shipment status.')
  }
  return response.json()
}

export async function reconcileCourierBooking(orderId: string): Promise<{ provider: string; shipment: Order['shipment'] }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/courier/reconcile`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not reconcile the courier booking.')
  return body
}

export async function refreshCourierTracking(orderId: string): Promise<{ provider: string; shipment: Order['shipment'] }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/courier/tracking/refresh`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not refresh courier tracking.')
  return body
}

export async function cancelCourierShipment(orderId: string): Promise<{ result: { status: string; message: string }; shipment: Order['shipment'] }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/courier/cancel`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: '{}' })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not cancel courier shipment.')
  return body
}

export async function syncShopifyFulfillment(orderId: string): Promise<{ order_id: string; shipment: Order['shipment'] }> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/shopify-fulfillment/sync`, { method: 'POST' })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || 'Could not synchronize Shopify fulfillment.')
  }
  return response.json()
}

export async function downloadShippingLabel(orderId: string): Promise<Blob> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/shipment/label`)
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
  const response = await apiFetch(`${apiBase}/api/v1/orders/${orderId}/address/validate`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload) })
  if (!response.ok) throw new Error('Could not validate address.')
  return response.json()
}

export async function exportOrders(mode: 'current' | 'full', orderIds: string[]): Promise<void> {
  const response = await apiFetch(`${apiBase}/api/v1/orders/export`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ mode, order_ids: orderIds }) })
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

export type DispatchRow = NonNullable<Order['shipment']> & { order_number?: string | null; customer_name?: string | null; payment_type?: string | null; order_value?: number | null }
export type DispatchQueue = { ready_to_ship: DispatchRow[]; manifested: DispatchRow[] }
export async function getLabelQueue(): Promise<DispatchQueue> {
  const response = await apiFetch(`${apiBase}/api/v1/labels/queue`)
  if (!response.ok) throw new Error('Could not load label queue.')
  return response.json()
}

export async function changeDispatchStage(orderIds:string[], stage:'manifest'|'ready'):Promise<{items:NonNullable<Order['shipment']>[];ready_to_ship_delta:number;manifested_delta:number}>{
  const response=await apiFetch(`${apiBase}/api/v1/labels/dispatch/${stage}`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({order_ids:orderIds,confirmed:true})})
  const body=await response.json().catch(()=>null)
  if(!response.ok)throw new Error(body?.detail||'Could not update dispatch stage.')
  return body
}

export async function createLabelBatch(orderIds: string[]): Promise<{ id: string; provider: string; status: string; order_ids: string[] }> {
  const response = await apiFetch(`${apiBase}/api/v1/labels/batches`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ order_ids: orderIds }) })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not create label batch.')
  return body
}

export async function confirmLabelBatch(batchId: string, printedOrderIds: string[]): Promise<void> {
  const response = await apiFetch(`${apiBase}/api/v1/labels/batches/${batchId}/confirm`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ printed_order_ids: printedOrderIds }) })
  if (!response.ok) throw new Error('Could not confirm label batch.')
}

export const labelBatchPdfUrl = (batchId: string) => `${apiBase}/api/v1/labels/batches/${batchId}/pdf`

export async function getActiveLabelBatches(): Promise<Array<{ id: string; provider: string; status: string; order_ids: string[] }>> {
  const response = await apiFetch(`${apiBase}/api/v1/labels/batches/active`)
  if (!response.ok) throw new Error('Could not recover pending print batches.')
  return response.json()
}

export async function requestLabelReprint(orderId: string): Promise<void> {
  const response = await apiFetch(`${apiBase}/api/v1/labels/orders/${orderId}/reprint`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ confirmed: true }) })
  if (!response.ok) throw new Error('Could not return the label to the print queue.')
}
