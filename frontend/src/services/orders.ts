export type RiskLevel = 'High' | 'Medium' | 'Low'

export interface OrderProduct {
  productName: string
  sku: string | null
  quantity: number
  weightGrams: number | null
  price: number
}

export interface Order {
  id: string
  date: string
  customer: string
  initials: string
  city: string
  state: string
  amount: number
  payment: 'COD' | 'Prepaid'
  customerType: 'Repeat Customer' | 'New Customer'
  risk: RiskLevel
  courier: string
  status: 'New' | 'Ready to book' | 'Booked' | 'In transit'
  phone: string | null
  email: string | null
  address: string | null
  pincode: string | null
  products: OrderProduct[]
  tags: string[]
}

interface ApiOrder {
  order_id: string; order_number: string; created_date: string; customer_name: string | null; phone: string | null; email: string | null
  shipping_address: { address: string | null; city: string | null; state: string | null; pincode: string | null } | null
  products: { product_name: string; sku: string | null; quantity: number; weight_grams: number | null; price: number }[]
  total_amount: number | string; payment_status: string | null; fulfillment_status: string | null; tags: string[]
}

const apiBase = 'http://127.0.0.1:8000'
const initials = (name: string) => name.split(' ').map(part => part[0]).join('').slice(0, 2).toUpperCase()

export async function getOrders(signal?: AbortSignal): Promise<Order[]> {
  const response = await fetch(`${apiBase}/api/v1/orders`, { signal })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail ?? 'Could not load Shopify orders.')
  }
  const data: ApiOrder[] = await response.json()
  return data.map((item): Order => {
    const name = item.customer_name || 'Guest customer'; const paymentStatus = (item.payment_status || '').toLowerCase()
    const fulfillment = (item.fulfillment_status || '').toLowerCase(); const tagText = item.tags.join(' ').toLowerCase()
    const payment = paymentStatus.includes('pending') || paymentStatus.includes('cod') ? 'COD' : 'Prepaid'
    const risk: RiskLevel = tagText.includes('high-risk') ? 'High' : tagText.includes('medium-risk') ? 'Medium' : 'Low'
    return { id: item.order_id, date: new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(item.created_date)), customer: name, initials: initials(name), city: item.shipping_address?.city || '—', state: item.shipping_address?.state || '—', amount: Number(item.total_amount), payment, customerType: tagText.includes('repeat') ? 'Repeat Customer' : 'New Customer', risk, courier: 'Delhivery', status: fulfillment.includes('fulfilled') ? 'In transit' : payment === 'COD' ? 'Ready to book' : 'New', phone: item.phone, email: item.email, address: item.shipping_address?.address || null, pincode: item.shipping_address?.pincode || null, products: item.products.map(product => ({ productName: product.product_name, sku: product.sku, quantity: product.quantity, weightGrams: product.weight_grams, price: Number(product.price) })), tags: item.tags }
  })
}
