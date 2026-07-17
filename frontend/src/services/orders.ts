export type RiskLevel = 'High' | 'Medium' | 'Low'

export interface OrderProduct {
  productName: string
  sku: string | null
  quantity: number
  weightGrams: number | null
  price: number
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
  payment: 'COD' | 'Prepaid'
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
  shipping_amount: number | string | null
  payment_status: string | null
  fulfillment_status: string | null
  shopify_status: string | null
  cancelled_at: string | null
  tags: string[]
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

const inferPayment = (paymentStatus: string | null): 'COD' | 'Prepaid' => {
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
      payment: inferPayment(item.payment_status),
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
      latestCallResult: item.latest_call_result,
      operationalStatus: item.operational_status,
      addressVerified: item.address_verified,
      addressVerifiedAt: item.address_verified_at,
      addressVerifiedBy: item.address_verified_by,
      verifiedAddressSnapshot: item.verified_address_snapshot,
      correctedAddress: item.corrected_address,
      courierSyncStatus: item.courier_sync_status,
      courierSyncError: item.courier_sync_error,
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
