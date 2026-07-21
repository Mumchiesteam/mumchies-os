import type { ReactNode } from 'react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  addOrderCallLog,
  bookShiprocketShipment,
  checkShiprocketCouriers,
  formatMoney,
  getBookingEligibility,
  getOrderOperations,
  getOrders,
  createLabelBatch,
  confirmLabelBatch,
  exportOrders,
  getLabelQueue,
  getActiveLabelBatches,
  labelBatchPdfUrl,
  requestLabelReprint,
  refreshShiprocketShipment,
  saveOrderAddress,
  saveOrderPackage,
  selectShiprocketCourier,
  shippingLabelUrl,
  syncShopifyFulfillment,
  verifyOrderAddress,
  validateAddress,
  type Order,
  type OrderOperations,
  type RiskLevel,
} from './services/orders'

type IconName = 'grid' | 'bag' | 'alert' | 'users' | 'chart' | 'settings' | 'search' | 'bell' | 'filter' | 'chevron' | 'more' | 'eye' | 'truck' | 'calendar' | 'close' | 'copy' | 'phone' | 'external' | 'repeat' | 'tag' | 'edit' | 'call'
type TabKey = 'fresh' | 'previous' | 'all'
type CallResult = 'No Answer' | 'Busy' | 'Switched Off' | 'Callback Requested' | 'Confirmed' | 'Cancelled' | 'Wrong Number'
type OperationalStatus = 'Call Pending' | 'Callback Required' | 'Address Verification Pending' | 'Ready for Booking' | 'Booked' | 'Shipped' | 'NDR' | 'Delivered' | 'Cancelled' | 'Needs Review'
type CourierQuote = {
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
}

const navItems = ['Dashboard', 'Orders', 'NDR', 'Customers', 'Reports', 'Settings'] as const
const tabItems: { key: TabKey; label: string }[] = [
  { key: 'fresh', label: 'Fresh Orders' },
  { key: 'previous', label: 'Previous Pending Orders' },
  { key: 'all', label: 'All Orders' },
]
const callResults: CallResult[] = ['No Answer', 'Busy', 'Switched Off', 'Callback Requested', 'Confirmed', 'Cancelled', 'Wrong Number']
const riskStyle: Record<RiskLevel, string> = { High: 'bg-rose-50 text-rose-700 ring-rose-100', Medium: 'bg-amber-50 text-amber-700 ring-amber-100', Low: 'bg-emerald-50 text-emerald-700 ring-emerald-100' }

const Icon = ({ name, size = 18 }: { name: IconName; size?: number }) => {
  const p: Record<IconName, ReactNode> = {
    grid: <><rect x="3" y="3" width="7" height="7" rx="1" /><rect x="14" y="3" width="7" height="7" rx="1" /><rect x="3" y="14" width="7" height="7" rx="1" /><rect x="14" y="14" width="7" height="7" rx="1" /></>,
    bag: <><path d="M5 8h14l-1 13H6L5 8Z" /><path d="M9 9V6a3 3 0 0 1 6 0v3" /></>,
    alert: <><path d="M10.3 3.3 2.4 17a2 2 0 0 0 1.7 3h15.8a2 2 0 0 0 1.7-3L13.7 3.3a2 2 0 0 0-3.4 0Z" /><path d="M12 9v4M12 17h.01" /></>,
    users: <><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2" /><circle cx="9" cy="7" r="4" /><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75" /></>,
    chart: <><path d="M4 19V5M4 19h17" /><path d="m7 15 4-4 3 2 5-6" /></>,
    settings: <><circle cx="12" cy="12" r="3" /><path d="M12 2v3M12 19v3M4.9 4.9 7 7M17 17l2.1 2.1M2 12h3M19 12h3M4.9 19.1 7 17M17 7l2.1-2.1" /></>,
    search: <><circle cx="11" cy="11" r="6" /><path d="m20 20-4-4" /></>,
    bell: <><path d="M18 8a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" /></>,
    filter: <path d="M4 5h16M7 12h10M10 19h4" />,
    chevron: <path d="m9 18 6-6-6-6" />,
    more: <><circle cx="5" cy="12" r="1" fill="currentColor" /><circle cx="12" cy="12" r="1" fill="currentColor" /><circle cx="19" cy="12" r="1" fill="currentColor" /></>,
    eye: <><path d="M2 12s3.5-6 10-6 10 6 10 6-3.5 6-10 6S2 12 2 12Z" /><circle cx="12" cy="12" r="2.5" /></>,
    truck: <><path d="M3 5h11v11H3zM14 9h4l3 3v4h-7z" /><circle cx="7" cy="18" r="2" /><circle cx="18" cy="18" r="2" /></>,
    calendar: <><rect x="3" y="5" width="18" height="16" rx="2" /><path d="M16 3v4M8 3v4M3 10h18" /></>,
    close: <path d="m6 6 12 12M18 6 6 18" />,
    copy: <><rect x="9" y="9" width="11" height="11" rx="2" /><path d="M15 9V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v8a2 2 0 0 0 2 2h4" /></>,
    phone: <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.8 2.1Z" />,
    external: <><path d="M14 3h7v7M21 3l-9 9" /><path d="M19 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2h6" /></>,
    repeat: <><path d="M17 1 21 5l-4 4" /><path d="M3 11a9 9 0 0 1 15-5" /><path d="M7 23 3 19l4-4" /><path d="M21 13a9 9 0 0 1-15 5" /></>,
    tag: <><path d="M20 12 12 20 3 11V3h8Z" /><circle cx="8" cy="8" r="1.5" /></>,
    edit: <><path d="M12 20h9" /><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" /></>,
    call: <path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1 1 .4 1.9.7 2.8a2 2 0 0 1-.5 2.1L8 9.9a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.5c.9.3 1.8.6 2.8.7a2 2 0 0 1 1.8 2.1Z" />,
  }
  return <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round">{p[name]}</svg>
}

const formatDate = (value: string) => new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value))
const formatOrderDateTime = (value: string) => {
  const date = new Date(value)
  return {
    date: new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }).format(date),
    time: new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }).format(date),
  }
}
const formatDateTime = (value: string) => new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
const isCancelled = (order: Order) => Boolean(order.cancelledAt || order.shopifyStatus === 'cancelled' || (order.payment === 'COD' && order.tags.join(' ').toLowerCase().includes('cancel')))
const isShipped = (order: Order) => {
  const status = `${order.fulfillmentStatus || ''} ${order.shopifyStatus || ''} ${order.tags.join(' ')}`.toLowerCase()
  return status.includes('fulfilled') || status.includes('partial') || status.includes('shipped') || status.includes('picked up') || status.includes('dispatched')
}
const isDelivered = (order: Order) => `${order.fulfillmentStatus || ''} ${order.shopifyStatus || ''} ${order.tags.join(' ')}`.toLowerCase().includes('delivered')
const isNdr = (order: Order) => `${order.tags.join(' ')} ${order.shopifyStatus || ''}`.toLowerCase().includes('ndr')
const listStatus = (order: Order): OperationalStatus => (order.operationalStatus as OperationalStatus | null) || (
  order.shipment?.awb || order.shipment?.shipment_id ? 'Booked'
    : isCancelled(order) ? 'Cancelled'
    : isDelivered(order) ? 'Delivered'
      : isShipped(order) || order.shopifyStatus === 'fulfilled' ? 'Shipped'
        : isNdr(order) ? 'NDR'
          : order.payment === 'Prepaid'
            ? order.addressVerified ? 'Ready for Booking' : 'Address Verification Pending'
            : order.latestCallResult === 'Callback Requested' ? 'Callback Required'
              : order.latestCallResult === 'Confirmed' ? 'Ready for Booking'
                : order.latestCallResult === 'Wrong Number' ? 'Needs Review'
                  : 'Call Pending'
)

function App() {
  const [orders, setOrders] = useState<Order[]>([])
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null)
  const [operations, setOperations] = useState<OrderOperations | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [queue, setQueue] = useState<TabKey>('all')
  const [search, setSearch] = useState('')
  const [payment, setPayment] = useState('All payments')
  const [risk, setRisk] = useState('All risks')
  const [sort, setSort] = useState('Newest first')
  const [cardFilter, setCardFilter] = useState<'pending' | 'cod' | 'prepaid' | 'risk' | 'repeat' | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const [notice, setNotice] = useState('')
  const [repeatIds, setRepeatIds] = useState<Set<string>>(new Set())
  const [callResult, setCallResult] = useState<CallResult>('No Answer')
  const [callComment, setCallComment] = useState('')
  const [bookingEligibility, setBookingEligibility] = useState<{
    eligible: boolean
    missing_requirements: string[]
    operational_status: string | null
    payment_mode: string | null
    shipment_exists: boolean
    shipment_status: string | null
    shipment: Order['shipment']
  } | null>(null)
  const [courierOptions, setCourierOptions] = useState<CourierQuote[]>([])
  const [courierLoading, setCourierLoading] = useState(false)
  const [courierError, setCourierError] = useState('')
  const [courierWarnings, setCourierWarnings] = useState<string[]>([])
  const [selectedCourierId, setSelectedCourierId] = useState<string | null>(null)
  const [bookingLoading, setBookingLoading] = useState(false)
  const bookingRequestInFlight = useRef(false)
  const [shipmentRefreshLoading, setShipmentRefreshLoading] = useState(false)
  const [shopifySyncLoading, setShopifySyncLoading] = useState(false)
  const [labelLoading, setLabelLoading] = useState(false)
  const [addressDraft, setAddressDraft] = useState({
    customer_name: '',
    phone: '',
    address_line1: '',
    address_line2: '',
    landmark: '',
    city: '',
    state: '',
    pincode: '',
  })
  const [updateCustomerAddress, setUpdateCustomerAddress] = useState(true)
  const [oneTimeDeliveryAddress, setOneTimeDeliveryAddress] = useState(false)
  const [useAsDefaultAddress, setUseAsDefaultAddress] = useState(false)
  const [labelQueue, setLabelQueue] = useState<{ labels_to_print: NonNullable<Order['shipment']>[]; awaiting_confirmation: NonNullable<Order['shipment']>[]; printed_today: NonNullable<Order['shipment']>[] }>({ labels_to_print: [], awaiting_confirmation: [], printed_today: [] })
  const [showLabels, setShowLabels] = useState(false)
  const [labelSearch, setLabelSearch] = useState('')
  const labelSearchRef = useRef<HTMLInputElement>(null)
  const [selectedLabels, setSelectedLabels] = useState<Set<string>>(new Set())
  const [activeBatch, setActiveBatch] = useState<{ id: string; order_ids: string[] } | null>(null)
  const [printedLabels, setPrintedLabels] = useState<Set<string>>(new Set())
  const refreshLabels = useCallback(() => void getLabelQueue().then(setLabelQueue).catch(() => undefined), [])

  const loadOrders = useCallback(async (signal?: AbortSignal) => {
    try {
      setError('')
      const data = await getOrders(signal)
      setOrders(data)
      const counts = new Map<string, number>()
      const repeat = new Set<string>()
      for (const order of data) {
        if (order.customerId) {
          const next = (counts.get(order.customerId) || 0) + 1
          counts.set(order.customerId, next)
          if (next > 1 || (order.customerOrdersCount || 0) > 1) repeat.add(order.internalId)
        }
      }
      setRepeatIds(repeat)
      setSelectedOrderId(current => current && data.some(order => order.internalId === current) ? current : null)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError((err as Error).message)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => void loadOrders(controller.signal), 0)
    return () => {
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [loadOrders])

  useEffect(() => { refreshLabels() }, [refreshLabels])

  useEffect(() => {
    if (selectedOrderId) return
    const interval = window.setInterval(() => void loadOrders(), 60_000)
    return () => window.clearInterval(interval)
  }, [loadOrders, selectedOrderId])

  useEffect(() => {
    if (!notice) return
    const timeout = window.setTimeout(() => setNotice(''), 3_000)
    return () => window.clearTimeout(timeout)
  }, [notice])

  const selectedOrder = useMemo(() => orders.find(order => order.internalId === selectedOrderId) || null, [orders, selectedOrderId])
  const queueOrders = useMemo(() => {
    const sortedNewestFirst = (a: Order, b: Order) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    const sortedOldestFirst = (a: Order, b: Order) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
    const active = (order: Order) => !isCancelled(order) && !isShipped(order) && !isDelivered(order)
    const unresolved = (order: Order) => active(order) && !['Ready for Booking', 'Booked'].includes(listStatus(order))
    return {
      fresh: orders.filter(order => active(order) && !order.firstActionAt),
      previous: orders.filter(order => Boolean(order.firstActionAt) && unresolved(order)),
      all: [...orders],
      sortedNewestFirst,
      sortedOldestFirst,
    }
  }, [orders])

  useEffect(() => {
    if (!selectedOrder) return
    let active = true
    void (async () => {
      const ops = await getOrderOperations(selectedOrder.internalId)
      if (!active) return
      setCourierOptions([])
      setCourierError('')
      setOperations(ops)
      setCallResult('No Answer')
      setCallComment('')
      setAddressDraft({
        customer_name: ops.corrected_address?.customer_name ?? selectedOrder.shippingAddress?.name ?? selectedOrder.customerName ?? '',
        phone: ops.corrected_address?.phone ?? selectedOrder.phone ?? '',
        address_line1: ops.corrected_address?.address_line1 ?? selectedOrder.shippingAddress?.address ?? '',
        address_line2: ops.corrected_address?.address_line2 ?? '',
        landmark: ops.corrected_address?.landmark ?? selectedOrder.shippingAddress?.landmark ?? '',
        city: ops.corrected_address?.city ?? selectedOrder.shippingAddress?.city ?? '',
        state: ops.corrected_address?.state ?? selectedOrder.shippingAddress?.state ?? '',
        pincode: ops.corrected_address?.pincode ?? selectedOrder.shippingAddress?.pincode ?? '',
      })
      setUpdateCustomerAddress(true)
      setOneTimeDeliveryAddress(false)
      setUseAsDefaultAddress(false)
      setSelectedCourierId(ops.selected_courier?.courier_id ?? null)
      const eligibility = await getBookingEligibility(selectedOrder.internalId)
      if (!active) return
      setBookingEligibility(eligibility)
    })().catch((err) => {
      if (!active) return
      setOperations(null)
      setCourierError((err as Error).message || 'Could not load order operations and courier eligibility.')
    })
    return () => { active = false }
  }, [selectedOrder])

  const openOrder = (orderId: string) => {
    setBookingEligibility(null)
    setCourierOptions([])
    setCourierError('')
    setSelectedOrderId(orderId)
  }

  const matchesSearch = useCallback((order: Order) => {
    const text = [
      order.orderNumber,
      order.customerName,
      order.phone,
      order.products.map(product => [product.productName, product.sku].filter(Boolean).join(' ')).join(' '),
    ].join(' ').toLowerCase()
    return text.includes(search.toLowerCase())
  }, [search])

  const queuePredicate = useCallback((order: Order) => {
    const active = !isCancelled(order) && !isShipped(order) && !isDelivered(order)
    if (queue === 'fresh') return active && !order.firstActionAt
    if (queue === 'previous') return active && Boolean(order.firstActionAt) && !['Ready for Booking', 'Booked'].includes(listStatus(order))
    return true
  }, [queue])

  const filtered = useMemo(() => {
    let list = orders.filter(order => matchesSearch(order) && (payment === 'All payments' || order.payment === payment) && (risk === 'All risks' || order.risk === risk) && queuePredicate(order))
    if (cardFilter === 'pending') list = list.filter(order => listStatus(order) === 'Ready for Booking' && !order.shipment?.awb)
    if (cardFilter === 'cod') list = list.filter(order => order.paymentType === 'cod' || order.paymentType === 'partial_cod')
    if (cardFilter === 'prepaid') list = list.filter(order => order.paymentType === 'prepaid')
    if (cardFilter === 'risk') list = list.filter(order => order.risk === 'High' && !isCancelled(order))
    if (cardFilter === 'repeat') list = list.filter(order => repeatIds.has(order.internalId))
    list = [...list].sort((a, b) => {
      if (queue === 'previous') return new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      if (sort === 'Oldest first') return new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
      if (sort === 'COD first') return Number(b.payment === 'COD') - Number(a.payment === 'COD') || new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      if (sort === 'Prepaid first') return Number(b.payment === 'Prepaid') - Number(a.payment === 'Prepaid') || new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
      if (sort === 'Value high to low') return b.amount - a.amount
      if (sort === 'Value low to high') return a.amount - b.amount
      return new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    })
    return list
  }, [orders, matchesSearch, payment, risk, queue, queuePredicate, sort, cardFilter, repeatIds])
  const displayedOrders = useMemo(() => filtered.slice(0, 250), [filtered])

  const summaryCounts = useMemo(() => ({
    fresh: queueOrders.fresh.length,
    previous: queueOrders.previous.length,
    all: queueOrders.all.length,
  }), [queueOrders])

  const cards = useMemo(() => {
    const pending = orders.filter(order => listStatus(order) === 'Ready for Booking' && !order.shipment?.awb)
    const cod = orders.filter(order => order.paymentType === 'cod' || order.paymentType === 'partial_cod')
    const prepaid = orders.filter(order => order.paymentType === 'prepaid')
    return [
      { key: 'new', label: 'New Orders', value: queueOrders.fresh.length, detail: 'No operator action' },
      { key: 'pending', label: 'Pending Booking', value: pending.length, detail: 'Ready to dispatch' },
      { key: 'cod', label: 'COD', value: cod.length, detail: `${formatMoney(cod.reduce((sum, order) => sum + order.codCollectableAmount, 0))} to collect` },
      { key: 'prepaid', label: 'Prepaid', value: prepaid.length, detail: formatMoney(prepaid.reduce((sum, order) => sum + order.orderTotal, 0)) },
      { key: 'risk', label: 'High Risk', value: orders.filter(order => order.risk === 'High' && !isCancelled(order)).length, detail: 'Active orders' },
      { key: 'repeat', label: 'Repeat Customers', value: orders.filter(order => repeatIds.has(order.internalId)).length, detail: 'Known customers' },
    ]
  }, [orders, queueOrders.fresh.length, repeatIds])

  const statusFromOrder = (order: Order): OperationalStatus => {
    return listStatus(order)
  }

  const callLog = [...(operations?.call_logs || [])].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
  const courierSyncMessage = operations?.courier_sync_error || ''
  const status = selectedOrder ? statusFromOrder(selectedOrder) : 'Call Pending'
  const isRepeat = selectedOrder ? repeatIds.has(selectedOrder.internalId) : false
  const visibleCount = filtered.length
  const addressVerifiedLabel = operations?.address_verified
    ? `Address Verified by ${operations.address_verified_by || 'operator'} on ${operations.address_verified_at ? formatDateTime(operations.address_verified_at) : 'unknown time'}`
    : 'Address Verification Pending'

  const refreshEligibility = async (orderId: string) => {
    const eligibility = await getBookingEligibility(orderId)
    setBookingEligibility(eligibility)
  }

  const saveCallLog = async () => {
    if (!selectedOrder) return
    try {
      const updated = await addOrderCallLog(selectedOrder.internalId, {
        result: callResult,
        operator: 'Amit Kumar',
        comment: callComment,
      })
      setOperations(updated)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, latestCallResult: updated.call_logs?.[0]?.result || null, operationalStatus: (updated.call_logs?.[0]?.result === 'Callback Requested' ? 'Callback Required' : updated.call_logs?.[0]?.result === 'Confirmed' ? (order.payment === 'Prepaid' && !updated.address_verified ? 'Address Verification Pending' : 'Ready for Booking') : updated.call_logs?.[0]?.result === 'Wrong Number' ? 'Needs Review' : updated.call_logs?.[0]?.result === 'Cancelled' ? 'Cancelled' : 'Call Pending') as OperationalStatus, addressVerified: updated.address_verified, addressVerifiedAt: updated.address_verified_at, addressVerifiedBy: updated.address_verified_by, verifiedAddressSnapshot: updated.verified_address_snapshot, correctedAddress: updated.corrected_address, courierSyncStatus: updated.courier_sync_status, courierSyncError: updated.courier_sync_error } : order))
      setCallComment('')
      await refreshEligibility(selectedOrder.internalId)
      setNotice('Call attempt saved')
    } catch (err) {
      setNotice((err as Error).message)
    }
  }

  const saveAddress = async () => {
    if (!selectedOrder) return
    try {
      const updated = await saveOrderAddress(selectedOrder.internalId, {
        ...addressDraft,
        courier_sync_status: operations?.courier_sync_status || 'Not synchronized',
        courier_sync_error: operations?.courier_sync_error || null,
        update_customer_address: updateCustomerAddress,
        one_time_delivery_address: oneTimeDeliveryAddress,
        use_as_default_address: useAsDefaultAddress,
      })
      setOperations(updated)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, addressVerified: updated.address_verified, addressVerifiedAt: updated.address_verified_at, addressVerifiedBy: updated.address_verified_by, verifiedAddressSnapshot: updated.verified_address_snapshot, correctedAddress: updated.corrected_address, courierSyncStatus: updated.courier_sync_status, courierSyncError: updated.courier_sync_error, addressSyncResults: updated.address_sync_results, operationalStatus: (order.payment === 'Prepaid' ? 'Address Verification Pending' : order.operationalStatus) as OperationalStatus | null } : order))
      await refreshEligibility(selectedOrder.internalId)
      setNotice('Address correction saved')
    } catch (err) {
      setNotice((err as Error).message)
    }
  }

  const verifyAddress = async () => {
    if (!selectedOrder) return
    try {
      const updated = await verifyOrderAddress(selectedOrder.internalId, {
      operator: 'Amit Kumar',
      address_snapshot: {
        customer_name: addressDraft.customer_name || null,
        phone: addressDraft.phone || null,
        address_line1: addressDraft.address_line1 || null,
        address_line2: addressDraft.address_line2 || null,
        landmark: addressDraft.landmark || null,
        city: addressDraft.city || null,
        state: addressDraft.state || null,
        pincode: addressDraft.pincode || null,
      },
      })
      setOperations(updated)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, addressVerified: updated.address_verified, addressVerifiedAt: updated.address_verified_at, addressVerifiedBy: updated.address_verified_by, verifiedAddressSnapshot: updated.verified_address_snapshot, correctedAddress: updated.corrected_address, courierSyncStatus: updated.courier_sync_status, courierSyncError: updated.courier_sync_error, operationalStatus: 'Ready for Booking' } : order))
      await refreshEligibility(selectedOrder.internalId)
      setNotice('Address verified')
    } catch (err) {
      setNotice((err as Error).message)
    }
  }

  const checkCouriers = async (packageNumbers: { weight_kg: number; length_cm: number | null; breadth_cm: number | null; height_cm: number | null }) => {
    if (!selectedOrder || !Number.isFinite(packageNumbers.weight_kg) || packageNumbers.weight_kg <= 0) return
    setCourierLoading(true)
    setCourierError('')
    setCourierWarnings([])
    setCourierOptions([])
    try {
      await saveOrderPackage(selectedOrder.internalId, packageNumbers)
      const result = await checkShiprocketCouriers(selectedOrder.internalId, {
        ...packageNumbers,
        courier_payment_mode: selectedOrder.payment,
      })
      const sorted = [...result.couriers].sort((a, b) => a.total_estimated_shipping_cost - b.total_estimated_shipping_cost)
      setCourierOptions(sorted)
      setCourierWarnings(result.provider_warnings ?? [])
      if (selectedCourierId && !sorted.some(courier => courier.courier_id === selectedCourierId)) {
        setSelectedCourierId(null)
      }
      await refreshEligibility(selectedOrder.internalId)
      setNotice('Courier options loaded')
    } catch (err) {
      setCourierError((err as Error).message)
    } finally {
      setCourierLoading(false)
    }
  }

  const selectCourier = async (courier: CourierQuote) => {
    if (!selectedOrder || !courier.courier_id) return
    setCourierError('')
    try {
      const result = await selectShiprocketCourier(selectedOrder.internalId, { ...courier, courier_id: courier.courier_id })
      setSelectedCourierId(result.selected_courier?.courier_id ?? courier.courier_id)
      setOperations(prev => prev ? { ...prev, selected_courier: result.selected_courier } : prev)
    } catch (err) {
      setCourierError((err as Error).message)
    }
  }

  const bookShipment = async (packageNumbers: { weight_kg: number; length_cm: number | null; breadth_cm: number | null; height_cm: number | null }) => {
    if (!selectedOrder || !selectedCourierId || !bookingEligibility?.eligible || bookingRequestInFlight.current) return
    const selectedQuote = courierOptions.find(option => option.courier_id === selectedCourierId)
    if (!selectedQuote?.booking_supported) return
    if (!window.confirm(`Book ${selectedQuote.courier_name} shipment for order #${selectedOrder.orderNumber}?`)) return
    bookingRequestInFlight.current = true
    setBookingLoading(true)
    setCourierError('')
    try {
      const result = await bookShiprocketShipment(selectedOrder.internalId, {
        provider: selectedQuote.provider,
        courier_name: selectedQuote.courier_name,
        courier_id: selectedCourierId,
        ...packageNumbers,
      })
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId
        ? { ...order, shipment: result.shipment ?? order.shipment, operationalStatus: 'Booked' }
        : order))
      setOperations(await getOrderOperations(selectedOrder.internalId))
      setNotice(result.existing ? 'Existing shipment loaded' : 'Shipment booked')
    } catch (err) {
      setCourierError((err as Error).message)
    } finally {
      bookingRequestInFlight.current = false
      setBookingLoading(false)
    }
  }

  const refreshShipment = async () => {
    if (!selectedOrder) return
    setShipmentRefreshLoading(true)
    setCourierError('')
    try {
      const result = await refreshShiprocketShipment(selectedOrder.internalId)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, shipment: result.shipment } : order))
      setOperations(await getOrderOperations(selectedOrder.internalId))
      setNotice('Shipment status refreshed')
    } catch (err) {
      setCourierError((err as Error).message)
    } finally {
      setShipmentRefreshLoading(false)
    }
  }

  const syncFulfillment = async () => {
    if (!selectedOrder) return
    setShopifySyncLoading(true)
    setCourierError('')
    try {
      const result = await syncShopifyFulfillment(selectedOrder.internalId)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, shipment: result.shipment } : order))
      setOperations(await getOrderOperations(selectedOrder.internalId))
      setNotice('Shopify fulfillment synchronized')
    } catch (err) {
      setCourierError((err as Error).message)
      const updated = await getOrderOperations(selectedOrder.internalId)
      setOperations(updated)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, shipment: updated.shipment } : order))
    } finally {
      setShopifySyncLoading(false)
    }
  }

  const retrieveLabel = (action: 'download' | 'print') => {
    if (!selectedOrder) return
    setCourierError('')
    setLabelLoading(true)
    const opened = window.open(
      shippingLabelUrl(selectedOrder.internalId, action === 'print' ? 'inline' : 'attachment'),
      '_blank',
    )
    if (opened) opened.opener = null
    else setCourierError('The label window was blocked. Allow pop-ups for Mumchies OS and try again.')
    window.setTimeout(() => setLabelLoading(false), 1_000)
  }

  return (
    <div className="min-h-screen bg-[#f8fafc] text-slate-900">
      <header className="sticky top-0 z-30 border-b border-slate-200 bg-white/90 backdrop-blur">
        <div className="mx-auto flex max-w-[1800px] items-center gap-4 px-4 py-4 lg:px-6">
          <div className="flex items-center gap-3">
            <div className="grid h-10 w-10 place-items-center rounded-xl bg-[#ff6b35] text-lg font-black text-white">m</div>
            <div>
              <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-400">Mumchies OS</p>
              <h1 className="text-lg font-bold tracking-tight">Operations Console</h1>
            </div>
          </div>
          <nav className="ml-2 hidden flex-1 gap-2 overflow-x-auto md:flex">
            {navItems.map(item => (
              <button key={item} className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${item === 'Orders' ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{item}</button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <button className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><Icon name="bell" /></button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1800px] px-4 py-5 lg:px-6">
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#ff6b35]">Orders</p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight">Operations queue <span className="font-medium text-slate-400">({visibleCount})</span></h2>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => void exportOrders('current', filtered.map(order => order.internalId)).catch(error => setNotice(error.message))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-600">Export Current View</button>
            <button onClick={() => void exportOrders('full', []).catch(error => setNotice(error.message))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-600">Export Full Workbook</button>
            <button onClick={() => void loadOrders()} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 shadow-sm hover:bg-slate-50">Refresh</button>
          </div>
        </div>

        <section className="mb-5 flex flex-wrap gap-2">
          {tabItems.map(tab => (
            <button key={tab.key} onClick={() => setQueue(tab.key)} className={`rounded-full px-4 py-2 text-sm font-medium ${queue === tab.key ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'}`}>
              {tab.label}
              <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] font-bold ${queue === tab.key ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-500'}`}>{summaryCounts[tab.key]}</span>
            </button>
          ))}
          <button onClick={() => { refreshLabels(); void getActiveLabelBatches().then(batches => { if (batches[0]) { setActiveBatch(batches[0]); setPrintedLabels(new Set(batches[0].order_ids)) } }); setShowLabels(true) }} className="rounded-full bg-white px-4 py-2 text-sm font-medium text-slate-600 ring-1 ring-slate-200">Labels to Print <span className="ml-2 font-bold">{labelQueue.labels_to_print.length}</span></button>
          <span className="rounded-full bg-white px-4 py-2 text-sm text-slate-500 ring-1 ring-slate-200">Awaiting Confirmation {labelQueue.awaiting_confirmation.length}</span>
          <span className="rounded-full bg-white px-4 py-2 text-sm text-slate-500 ring-1 ring-slate-200">Printed Today {labelQueue.printed_today.length}</span>
        </section>

        <section className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          {cards.map(card => {
            const active = card.key === 'new' ? queue === 'fresh' && !cardFilter : cardFilter === card.key
            return <button key={card.key} onClick={() => { if (card.key === 'new') { setQueue('fresh'); setCardFilter(null) } else { setQueue('all'); setCardFilter(card.key as typeof cardFilter) } }} className={`rounded-xl border bg-white p-3 text-left shadow-sm transition ${active ? 'border-orange-300 ring-2 ring-orange-100' : 'border-slate-200 hover:border-slate-300'}`}>
              <p className="text-xs font-semibold text-slate-500">{card.label}</p>
              <p className="mt-1 text-xl font-bold text-slate-900">{card.value}</p>
              <p className="mt-1 truncate text-[11px] text-slate-400">{card.detail}</p>
            </button>
          })}
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-4 border-b border-slate-200 p-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="relative min-w-0 flex-1 xl:max-w-sm">
              <span className="absolute left-3 top-3 text-slate-400"><Icon name="search" size={17} /></span>
              <input ref={searchRef} value={search} onChange={e => setSearch(e.target.value)} className="w-full rounded-lg border border-slate-200 py-2.5 pl-9 pr-9 text-sm outline-none placeholder:text-slate-400 focus:border-orange-300 focus:ring-2 focus:ring-orange-100" placeholder="Search by order or customer..." />
              {search && <button aria-label="Clear search" onClick={() => { setSearch(''); searchRef.current?.focus() }} className="absolute right-3 top-2.5 text-lg text-slate-400 hover:text-slate-700">×</button>}
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Filter value={payment} onChange={setPayment} options={['All payments', 'COD', 'Partial COD', 'Prepaid']} />
              <Filter value={risk} onChange={setRisk} options={['All risks', 'High', 'Medium', 'Low']} />
              <Filter value={sort} onChange={setSort} options={['Newest first', 'Oldest first', 'COD first', 'Prepaid first', 'Value high to low', 'Value low to high']} />
            </div>
          </div>

          {loading ? (
            <div className="grid min-h-80 place-items-center">
              <div className="text-center">
                <span className="mx-auto block h-8 w-8 animate-spin rounded-full border-2 border-orange-200 border-t-[#ff6b35]" />
                <p className="mt-3 text-sm font-medium text-slate-500">Loading Shopify orders…</p>
              </div>
            </div>
          ) : error ? (
            <div className="grid min-h-80 place-items-center px-6 text-center">
              <div>
                <p className="text-sm font-semibold text-slate-700">Unable to load orders</p>
                <p className="mt-1 max-w-md text-sm text-slate-500">{error}</p>
              </div>
            </div>
          ) : (
            <>
              <div className="overflow-x-auto">
                <table className="w-full min-w-[980px] text-left">
                  <thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-400">
                    <tr>
                      {['Order No', 'Date / Time', 'Customer', 'Amount', 'Payment', 'Risk', 'Status', 'Actions'].map(column => <th key={column} className="whitespace-nowrap px-4 py-3.5">{column}</th>)}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {displayedOrders.map(order => <OrderRow key={order.internalId} order={order} repeat={repeatIds.has(order.internalId)} onClick={() => openOrder(order.internalId)} />)}
                  </tbody>
                </table>
                {filtered.length === 0 && <div className="py-14 text-center text-sm text-slate-400">No orders match your filters.</div>}
              </div>
              <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
                <p className="text-xs text-slate-500">Showing <span className="font-semibold text-slate-700">{displayedOrders.length}</span> of {filtered.length} matching orders</p>
                <p className="text-xs text-slate-400">Fresh, actioned-pending and complete order views.</p>
              </div>
            </>
          )}
        </section>
      </main>

      {selectedOrder && (
        <OrderDrawer
          key={selectedOrder.internalId}
          order={selectedOrder}
          repeat={isRepeat}
          status={status}
          callLog={callLog}
          callResult={callResult}
          callComment={callComment}
          setCallResult={setCallResult}
          setCallComment={setCallComment}
          addressDraft={addressDraft}
          setAddressDraft={setAddressDraft}
          updateCustomerAddress={updateCustomerAddress}
          oneTimeDeliveryAddress={oneTimeDeliveryAddress}
          useAsDefaultAddress={useAsDefaultAddress}
          setUpdateCustomerAddress={setUpdateCustomerAddress}
          setOneTimeDeliveryAddress={setOneTimeDeliveryAddress}
          setUseAsDefaultAddress={setUseAsDefaultAddress}
          courierSyncMessage={courierSyncMessage}
          addressVerificationLine={addressVerifiedLabel}
          onClose={() => setSelectedOrderId(null)}
          onSaveCallLog={() => void saveCallLog()}
          onSaveAddress={() => void saveAddress()}
          onVerifyAddress={() => void verifyAddress()}
          bookingEligibility={bookingEligibility}
          courierOptions={courierOptions}
          courierLoading={courierLoading}
          bookingLoading={bookingLoading}
          shipmentRefreshLoading={shipmentRefreshLoading}
          shopifySyncLoading={shopifySyncLoading}
          labelLoading={labelLoading}
          courierError={courierError}
          courierWarnings={courierWarnings}
          selectedCourierId={selectedCourierId}
          onCheckCouriers={checkCouriers}
          onSelectCourier={courier => void selectCourier(courier)}
          onBookShipment={bookShipment}
          onRefreshShipment={() => void refreshShipment()}
          onSyncShopifyFulfillment={() => void syncFulfillment()}
          onDownloadLabel={() => retrieveLabel('download')}
          onPrintLabel={() => retrieveLabel('print')}
        />
      )}

      {notice && <div className="fixed bottom-5 right-5 z-[60] rounded-lg bg-slate-900 px-4 py-3 text-sm font-medium text-white shadow-xl">{notice}</div>}
      {showLabels && <div className="fixed inset-0 z-[70] grid place-items-center bg-slate-950/40 p-4"><div className="max-h-[85vh] w-full max-w-3xl overflow-y-auto rounded-xl bg-white p-5 shadow-2xl">
        <div className="flex items-center justify-between"><div><h2 className="text-lg font-bold">Labels to Print</h2><p className="text-xs text-slate-500">One provider per batch · generating a PDF does not mark labels printed.</p></div><button onClick={() => setShowLabels(false)} className="text-slate-500">Close</button></div>
        <div className="relative mt-4"><input ref={labelSearchRef} value={labelSearch} onChange={event => setLabelSearch(event.target.value)} placeholder="Search order, AWB or customer" className="w-full rounded-lg border border-slate-200 px-3 py-2 pr-9 text-sm" />{labelSearch && <button onClick={() => { setLabelSearch(''); labelSearchRef.current?.focus() }} className="absolute right-3 top-1.5 text-lg text-slate-400">×</button>}</div>
        <div className="mt-4 space-y-2">{labelQueue.labels_to_print.filter(shipment => { const order = orders.find(value => value.internalId === shipment.order_id); return `${order?.orderNumber || ''} ${order?.customerName || ''} ${shipment.awb || ''}`.toLowerCase().includes(labelSearch.toLowerCase()) }).map(shipment => { const order = orders.find(value => value.internalId === shipment.order_id); const checked = selectedLabels.has(String(shipment.order_id)); return <label key={shipment.order_id} className="flex items-center gap-3 rounded-lg border border-slate-200 p-3 text-sm"><input type="checkbox" checked={checked} onChange={() => setSelectedLabels(previous => { const next = new Set(previous); if (checked) next.delete(String(shipment.order_id)); else next.add(String(shipment.order_id)); return next })} /><span className="font-semibold">#{order?.orderNumber || shipment.order_id}</span><span>{order?.customerName || 'Customer'}</span><span className="ml-auto text-xs text-slate-500">{shipment.provider} · {shipment.awb}</span></label>})}</div>
        {labelQueue.printed_today.length > 0 && <details className="mt-4"><summary className="cursor-pointer text-sm font-semibold text-slate-600">Previously printed</summary><div className="mt-2 space-y-2">{labelQueue.printed_today.map(shipment => <div key={shipment.order_id} className="flex items-center gap-2 rounded-lg bg-slate-50 p-2 text-xs"><span>#{orders.find(order => order.internalId === shipment.order_id)?.orderNumber || shipment.order_id}</span><span>Printed {shipment.label_last_printed_at ? formatDateTime(shipment.label_last_printed_at) : ''}</span><button onClick={() => { if (window.confirm('Print this label again?')) void requestLabelReprint(String(shipment.order_id)).then(refreshLabels).catch(error => setNotice(error.message)) }} className="ml-auto font-semibold text-slate-700">Print again?</button></div>)}</div></details>}
        {!activeBatch ? <button disabled={!selectedLabels.size} onClick={() => void createLabelBatch([...selectedLabels]).then(batch => { setActiveBatch(batch); setPrintedLabels(new Set(batch.order_ids)); window.open(labelBatchPdfUrl(batch.id), '_blank', 'noopener,noreferrer'); refreshLabels() }).catch(error => setNotice(error.message))} className="mt-4 rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white disabled:opacity-40">Print Selected</button> : <div className="mt-5 rounded-lg bg-amber-50 p-4"><p className="font-semibold text-amber-900">Were all labels printed successfully?</p><p className="mt-1 text-xs text-amber-700">Uncheck failed labels before confirming partial success.</p><div className="mt-3 space-y-1">{activeBatch.order_ids.map(id => <label key={id} className="flex gap-2 text-sm"><input type="checkbox" checked={printedLabels.has(id)} onChange={() => setPrintedLabels(previous => { const next = new Set(previous); if (next.has(id)) next.delete(id); else next.add(id); return next })} />#{orders.find(order => order.internalId === id)?.orderNumber || id}</label>)}</div><div className="mt-3 flex flex-wrap gap-2"><button onClick={() => void confirmLabelBatch(activeBatch.id, activeBatch.order_ids).then(() => { setActiveBatch(null); setSelectedLabels(new Set()); refreshLabels() })} className="rounded-lg bg-slate-900 px-3 py-2 text-sm font-semibold text-white">Mark all printed</button><button onClick={() => void confirmLabelBatch(activeBatch.id, [...printedLabels]).then(() => { setActiveBatch(null); setSelectedLabels(new Set()); refreshLabels() })} className="rounded-lg border border-amber-300 px-3 py-2 text-sm font-semibold">Confirm selected only</button><button onClick={() => void confirmLabelBatch(activeBatch.id, []).then(() => { setActiveBatch(null); setSelectedLabels(new Set()); refreshLabels() })} className="rounded-lg px-3 py-2 text-sm">Return all to queue</button><button onClick={() => window.open(labelBatchPdfUrl(activeBatch.id), '_blank', 'noopener,noreferrer')} className="rounded-lg px-3 py-2 text-sm">Reopen PDF</button></div></div>}
      </div></div>}
    </div>
  )
}

function Filter({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: string[] }) {
  return <select value={value} onChange={e => onChange(e.target.value)} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium text-slate-600 outline-none focus:border-orange-300">{options.map(option => <option key={option}>{option}</option>)}</select>
}

const OrderRow = memo(function OrderRow({ order, repeat, onClick }: { order: Order; repeat: boolean; onClick: () => void }) {
  const statusText = listStatus(order)
  const placed = formatOrderDateTime(order.createdAt)
  const attempt = order.callAttemptCount > 0 ? `Attempt ${order.callAttemptCount > 5 ? '5+' : order.callAttemptCount}` : null
  const status = statusText === 'Booked' || statusText === 'Shipped' || statusText === 'Delivered' ? 'bg-emerald-50 text-emerald-700' : statusText === 'Cancelled' || statusText === 'Needs Review' ? 'bg-rose-50 text-rose-700' : statusText === 'NDR' ? 'bg-violet-50 text-violet-700' : statusText === 'Address Verification Pending' || statusText === 'Call Pending' || statusText === 'Callback Required' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-700'
  return (
    <tr onClick={onClick} style={{ contentVisibility: 'auto', containIntrinsicSize: '0 56px' }} className="cursor-pointer text-sm text-slate-600 hover:bg-orange-50/50">
      <td className="px-4 py-3.5 font-semibold text-slate-800">{order.orderNumber}</td>
      <td className="whitespace-nowrap px-4 py-3.5"><p className="font-medium text-slate-700">{placed.date}</p><p className="text-xs text-slate-400">{placed.time}</p></td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          {order.customerId && <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${repeat ? 'bg-violet-50 text-violet-700' : 'bg-slate-100 text-slate-600'}`}>{repeat ? '[RPT]' : '[NEW]'}</span>}
          <span className="font-medium text-slate-700">{order.customerName}</span>
        </div>
      </td>
      <td className="px-4 py-3.5 font-semibold text-slate-800">{formatMoney(order.amount)}</td>
      <td className="px-4 py-3.5"><span className={`rounded-md px-2 py-1 text-[11px] font-bold ${order.payment === 'Prepaid' ? 'bg-emerald-50 text-emerald-700' : order.payment === 'Partial COD' ? 'bg-orange-100 text-orange-800' : 'bg-amber-50 text-amber-700'}`}>{order.payment}</span>{order.payment !== 'Prepaid' && attempt && <p className="mt-1 text-[10px] font-semibold text-slate-400">{attempt}</p>}{order.payment === 'Partial COD' && <p className="mt-1 whitespace-nowrap text-[10px] text-slate-500">{formatMoney(order.paidAmount)} paid · {formatMoney(order.codCollectableAmount)} due</p>}</td>
      <td className="px-4 py-3.5"><span className={`rounded-md px-2 py-1 text-[11px] font-bold ring-1 ring-inset ${riskStyle[order.risk]}`}>{order.risk} Risk</span></td>
      <td className="px-4 py-3.5"><span className={`whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-bold ${status}`}>{statusText}</span></td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-1">
          <button onClick={e => { e.stopPropagation(); onClick() }} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Icon name="eye" size={16} /></button>
        </div>
      </td>
    </tr>
  )
})

const OrderDrawer = memo(function OrderDrawer({
  order,
  repeat,
  status,
  callLog,
  callResult,
  callComment,
  setCallResult,
  setCallComment,
  addressDraft,
  setAddressDraft,
  updateCustomerAddress,
  oneTimeDeliveryAddress,
  useAsDefaultAddress,
  setUpdateCustomerAddress,
  setOneTimeDeliveryAddress,
  setUseAsDefaultAddress,
  courierSyncMessage,
  addressVerificationLine,
  onClose,
  onSaveCallLog,
  onSaveAddress,
  onVerifyAddress,
  bookingEligibility,
  courierOptions,
  courierLoading,
  bookingLoading,
  shipmentRefreshLoading,
  shopifySyncLoading,
  labelLoading,
  courierError,
  courierWarnings,
  selectedCourierId,
  onCheckCouriers,
  onSelectCourier,
  onBookShipment,
  onRefreshShipment,
  onSyncShopifyFulfillment,
  onDownloadLabel,
  onPrintLabel,
}: {
  order: Order
  repeat: boolean
  status: string
  callLog: OrderOperations['call_logs']
  callResult: CallResult
  callComment: string
  setCallResult: (value: CallResult) => void
  setCallComment: (value: string) => void
  addressDraft: {
    customer_name: string
    phone: string
    address_line1: string
    address_line2: string
    landmark: string
    city: string
    state: string
    pincode: string
  }
  setAddressDraft: (value: {
    customer_name: string
    phone: string
    address_line1: string
    address_line2: string
    landmark: string
    city: string
    state: string
    pincode: string
  }) => void
  updateCustomerAddress: boolean
  oneTimeDeliveryAddress: boolean
  useAsDefaultAddress: boolean
  setUpdateCustomerAddress: (value: boolean) => void
  setOneTimeDeliveryAddress: (value: boolean) => void
  setUseAsDefaultAddress: (value: boolean) => void
  courierSyncMessage: string
  addressVerificationLine: string
  onClose: () => void
  onSaveCallLog: () => void
  onSaveAddress: () => void
  onVerifyAddress: () => void
  bookingEligibility: {
    eligible: boolean
    missing_requirements: string[]
    operational_status: string | null
    payment_mode: string | null
    shipment_exists: boolean
    shipment_status: string | null
    shipment: Order['shipment']
  } | null
  courierOptions: CourierQuote[]
  courierLoading: boolean
  bookingLoading: boolean
  shipmentRefreshLoading: boolean
  shopifySyncLoading: boolean
  labelLoading: boolean
  courierError: string
  courierWarnings: string[]
  selectedCourierId: string | null
  onCheckCouriers: (packageNumbers: {
    weight_kg: number
    length_cm: number | null
    breadth_cm: number | null
    height_cm: number | null
  }) => void
  onSelectCourier: (courier: CourierQuote) => void
  onBookShipment: (packageNumbers: {
    weight_kg: number
    length_cm: number | null
    breadth_cm: number | null
    height_cm: number | null
  }) => void
  onRefreshShipment: () => void
  onSyncShopifyFulfillment: () => void
  onDownloadLabel: () => void
  onPrintLabel: () => void
}) {
  const [packageDraft, setPackageDraft] = useState(() => ({
    weight_kg: order.packageDetails?.weight_kg?.toString() || (order.products.reduce((sum, product) => sum + (product.weightGrams ? product.weightGrams * product.quantity : 0), 0) > 0 ? (order.products.reduce((sum, product) => sum + (product.weightGrams ? product.weightGrams * product.quantity : 0), 0) / 1000).toFixed(2) : ''),
    length_cm: order.packageDetails?.length_cm?.toString() || '5',
    breadth_cm: order.packageDetails?.breadth_cm?.toString() || '5',
    height_cm: order.packageDetails?.height_cm?.toString() || '5',
  }))
  const [addressReview, setAddressReview] = useState<{ status: string; blockers: string[]; warnings: string[]; shiprocket_message: string } | null>(null)
  const [addressReviewLoading, setAddressReviewLoading] = useState(false)

  const shipping = order.shippingAmount == null ? 'Courier rates not connected' : formatMoney(order.shippingAmount)
  const verificationLine = addressVerificationLine
  const hasVerifiedAddress = verificationLine.startsWith('Address Verified by')
  const isPrepaid = order.payment === 'Prepaid'
  const shipment = order.shipment
  const missing = bookingEligibility?.missing_requirements ?? []
  const packageWeight = Number(packageDraft.weight_kg)
  const packageDimensions = [packageDraft.length_cm, packageDraft.breadth_cm, packageDraft.height_cm].map(Number)
  const packageValid = Number.isFinite(packageWeight) && packageWeight > 0 && packageDimensions.every(value => Number.isFinite(value) && value > 0)
  const packageNumbers = useMemo(() => ({
    weight_kg: packageDraft.weight_kg ? Number(packageDraft.weight_kg) : NaN,
    length_cm: packageDraft.length_cm ? Number(packageDraft.length_cm) : null,
    breadth_cm: packageDraft.breadth_cm ? Number(packageDraft.breadth_cm) : null,
    height_cm: packageDraft.height_cm ? Number(packageDraft.height_cm) : null,
  }), [packageDraft])
  const packageRequirementNames = new Set(['package weight', 'package length', 'package breadth', 'package height'])
  const nonPackageMissing = missing.filter(requirement => !packageRequirementNames.has(requirement.toLowerCase()))
  const canCheckCouriers = bookingEligibility !== null && packageValid && nonPackageMissing.length === 0
  const selectedCourier = courierOptions.find(option => option.courier_id === selectedCourierId)
  const canBookShipment = bookingEligibility !== null
    && nonPackageMissing.length === 0
    && packageValid
    && Boolean(selectedCourierId)
    && Boolean(selectedCourier?.booking_supported)
    && !bookingEligibility.shipment_exists
    && !bookingLoading
  const requirementLabels: Record<string, string> = {
    'latest call must be Confirmed': 'COD confirmation required',
    'address must be verified': 'Address verification required',
    'delivery postcode': 'Delivery postcode missing',
    'latest operational address': 'Operational address missing',
    'pickup location': 'Pickup location unavailable',
    'package weight': 'Package weight missing',
    'package length': 'Package length missing',
    'package breadth': 'Package breadth missing',
    'package height': 'Package height missing',
    'operational status must be Ready for Booking': 'Order status must be Ready for Booking',
  }
  const visibleMissing = [
    ...nonPackageMissing.map(requirement => requirementLabels[requirement] || requirement),
    ...(!packageDraft.weight_kg || !Number.isFinite(packageWeight) || packageWeight <= 0 ? ['Package weight missing'] : []),
    ...(!packageDraft.length_cm || !Number.isFinite(packageDimensions[0]) || packageDimensions[0] <= 0 ? ['Package length missing'] : []),
    ...(!packageDraft.breadth_cm || !Number.isFinite(packageDimensions[1]) || packageDimensions[1] <= 0 ? ['Package breadth missing'] : []),
    ...(!packageDraft.height_cm || !Number.isFinite(packageDimensions[2]) || packageDimensions[2] <= 0 ? ['Package height missing'] : []),
  ]

  return (
    <div className="fixed inset-0 z-40">
      <button aria-label="Close order drawer" onClick={onClose} className="absolute inset-0 bg-slate-950/35 backdrop-blur-[1px]" />
      <aside className="absolute inset-y-0 right-0 flex h-full w-[92vw] max-w-[760px] flex-col bg-white shadow-2xl md:w-[46vw]">
        <header className="border-b border-slate-200 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-slate-400">Order details</p>
            <h2 className="mt-0.5 text-lg font-bold">Order #{order.orderNumber}</h2>
            <div className="mt-2 flex flex-wrap items-center gap-2 text-xs font-semibold text-slate-600">
                <span className="rounded-full bg-amber-50 px-2.5 py-1 text-amber-700">{order.payment}</span>
                <span className={`rounded-full px-2.5 py-1 ${status === 'Booked' ? 'bg-emerald-50 text-emerald-700' : status === 'Cancelled' ? 'bg-rose-50 text-rose-700' : 'bg-slate-100 text-slate-700'}`}>{status}</span>
                <span className={`rounded-full px-2.5 py-1 ${riskStyle[order.risk]}`}>{order.risk} Risk</span>
                <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">{formatDate(order.createdAt)}</span>
              <span className="rounded-full bg-slate-100 px-2.5 py-1 text-slate-700">{formatMoney(order.amount)}</span>
            </div>
          </div>
            <button onClick={onClose} className="rounded-lg p-2 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Icon name="close" /></button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto pb-24">
          <Section title="Customer">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <KeyValue label="Customer Name" value={order.customerName} />
              <KeyValue label="Mobile" value={order.phone || 'No phone'} />
              <KeyValue label="Email" value={order.email || 'No email'} />
              {order.customerId ? <KeyValue label="Customer Type" value={repeat ? '[RPT]' : '[NEW]'} /> : <KeyValue label="Customer Type" value="—" />}
            </div>
          </Section>

          <Section title="Shipping Address">
            <div className="mb-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-600">
              <p className={`font-medium ${hasVerifiedAddress ? 'text-emerald-700' : 'text-amber-700'}`}>{verificationLine}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Customer Name" value={addressDraft.customer_name} onChange={value => setAddressDraft({ ...addressDraft, customer_name: value })} />
              <Field label="Phone" value={addressDraft.phone} onChange={value => setAddressDraft({ ...addressDraft, phone: value })} />
              <Field label="Address Line 1" value={addressDraft.address_line1} onChange={value => setAddressDraft({ ...addressDraft, address_line1: value })} />
              <Field label="Address Line 2" value={addressDraft.address_line2} onChange={value => setAddressDraft({ ...addressDraft, address_line2: value })} />
              <Field label="Landmark" value={addressDraft.landmark} onChange={value => setAddressDraft({ ...addressDraft, landmark: value })} />
              <Field label="City" value={addressDraft.city} onChange={value => setAddressDraft({ ...addressDraft, city: value })} />
              <Field label="State" value={addressDraft.state} onChange={value => setAddressDraft({ ...addressDraft, state: value })} />
              <Field label="PIN Code" value={addressDraft.pincode} onChange={value => setAddressDraft({ ...addressDraft, pincode: value })} />
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={onSaveAddress} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white">Save Correction</button>
              {isPrepaid && <button onClick={onVerifyAddress} disabled={hasVerifiedAddress} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-600 disabled:cursor-not-allowed disabled:opacity-50">Address Verified</button>}
              <button onClick={() => { setAddressReviewLoading(true); void validateAddress(order.internalId, addressDraft).then(setAddressReview).catch(error => setAddressReview({ status: error.message, blockers: [], warnings: [], shiprocket_message: 'Shiprocket confidence score unavailable' })).finally(() => setAddressReviewLoading(false)) }} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600">{addressReviewLoading ? 'Validating…' : 'Validate Address'}</button>
              <button onClick={() => { const query = [addressDraft.address_line1, addressDraft.address_line2, addressDraft.landmark, addressDraft.city, addressDraft.state, addressDraft.pincode, 'India'].filter(Boolean).join(', '); window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`, '_blank', 'noopener,noreferrer') }} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600">Open in Google Maps</button>
            </div>
            {addressReview && <div className={`mt-3 rounded-lg px-3 py-2 text-sm ${addressReview.blockers.length ? 'bg-rose-50 text-rose-700' : addressReview.warnings.length ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-700'}`}><p className="font-semibold">{addressReview.status}</p>{addressReview.blockers.map(value => <p key={value}>• {value}</p>)}{addressReview.warnings.map(value => <p key={value}>• {value}</p>)}<p className="mt-1 text-xs opacity-80">{addressReview.shiprocket_message}</p><p className="mt-1 text-[11px] opacity-70">Advisory only; Maps results and warnings do not block verification.</p></div>}
            <div className="mt-3 space-y-2 text-xs text-slate-600">
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={updateCustomerAddress} onChange={event => { setUpdateCustomerAddress(event.target.checked); if (event.target.checked) setOneTimeDeliveryAddress(false) }} />
                Update customer's saved Shopify address
              </label>
              <label className="flex items-center gap-2">
                <input type="checkbox" checked={oneTimeDeliveryAddress} onChange={event => { setOneTimeDeliveryAddress(event.target.checked); if (event.target.checked) { setUpdateCustomerAddress(false); setUseAsDefaultAddress(false) } }} />
                One-time delivery address — do not update customer account
              </label>
              {updateCustomerAddress && !oneTimeDeliveryAddress && (
                <label className="flex items-center gap-2 pl-5">
                  <input type="checkbox" checked={useAsDefaultAddress} onChange={event => setUseAsDefaultAddress(event.target.checked)} />
                  Use as default address for future orders
                </label>
              )}
              {order.addressSyncResults && (
                <div className="grid grid-cols-2 gap-1 rounded-lg bg-slate-50 p-2">
                  <span>Shopify order: {order.addressSyncResults.shopify_order}</span>
                  <span>Shopify customer: {order.addressSyncResults.shopify_customer}</span>
                  <span>Shiprocket: {order.addressSyncResults.shiprocket}</span>
                  <span>Delhivery: {order.addressSyncResults.delhivery}</span>
                </div>
              )}
            </div>
          </Section>

          <Section title="Products">
            <div className="space-y-3">
              {order.products.map(product => (
                <div key={`${order.internalId}-${product.productName}-${product.sku || 'na'}`} className="rounded-lg border border-slate-100 p-3">
                  <div className="flex justify-between gap-3">
                    <div>
                      <p className="text-sm font-semibold">{product.productName}</p>
                      <p className="mt-1 text-xs text-slate-400">{product.sku || 'No SKU'} · {product.weightGrams ? `${product.weightGrams} g` : 'No weight'}</p>
                    </div>
                    <p className="text-sm font-bold">{formatMoney(product.price)}</p>
                  </div>
                  <div className="mt-2 flex justify-between text-xs text-slate-500">
                    <span>Qty: {product.quantity}</span>
                    <span>Total: {formatMoney(product.price * product.quantity)}</span>
                  </div>
                </div>
              ))}
            </div>
          </Section>

          <Section title="COD Call Log">
            <div className="space-y-3">
              <div className="grid gap-2 lg:grid-cols-[1fr_2fr_auto]">
                <select value={callResult} onChange={e => setCallResult(e.target.value as CallResult)} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none">
                  {callResults.map(result => <option key={result}>{result}</option>)}
                </select>
                <input value={callComment} onChange={e => setCallComment(e.target.value)} placeholder="Comment" className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none" />
                <button onClick={onSaveCallLog} className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white">Save</button>
              </div>
              <div className="space-y-2">
                {callLog.length === 0 ? <p className="text-sm text-slate-400">No call attempts logged yet.</p> : callLog.map(entry => (
                  <div key={`${entry.timestamp}-${entry.result}`} className="rounded-lg border border-slate-100 px-3 py-2 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-700">{entry.result}</span>
                      <span className="text-xs text-slate-400">{entry.timestamp}</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">Operator: {entry.operator}</p>
                    {entry.comment && <p className="mt-1 text-xs text-slate-600">{entry.comment}</p>}
                  </div>
                ))}
              </div>
            </div>
          </Section>

          <Section title="Courier Booking">
            <div className="space-y-4 text-sm text-slate-600">
              <div className="grid gap-3 sm:grid-cols-4">
                <Field testId="package-weight" label="Weight (kg)" value={packageDraft.weight_kg} onChange={value => setPackageDraft({ ...packageDraft, weight_kg: value })} />
                <Field testId="package-length" label="Length (cm)" value={packageDraft.length_cm} onChange={value => setPackageDraft({ ...packageDraft, length_cm: value })} />
                <Field testId="package-breadth" label="Breadth (cm)" value={packageDraft.breadth_cm} onChange={value => setPackageDraft({ ...packageDraft, breadth_cm: value })} />
                <Field testId="package-height" label="Height (cm)" value={packageDraft.height_cm} onChange={value => setPackageDraft({ ...packageDraft, height_cm: value })} />
              </div>
              <div className="flex flex-wrap gap-2">
                <button disabled={!canCheckCouriers || courierLoading} onClick={() => void onCheckCouriers(packageNumbers)} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-300">Check Couriers</button>
                <button disabled={!canBookShipment} onClick={() => void onBookShipment(packageNumbers)} className="rounded-lg border border-slate-200 px-4 py-2 text-sm font-semibold text-slate-700 disabled:cursor-not-allowed disabled:bg-slate-100 disabled:text-slate-400">{bookingLoading ? (selectedCourier?.provider === 'delhivery' ? 'Booking with Delhivery…' : 'Booking…') : selectedCourier?.provider === 'shadowfax' ? 'Manual booking only' : 'Book Shipment'}</button>
              </div>
              <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                <p className="font-medium text-slate-700">Eligibility</p>
                {bookingEligibility === null
                  ? <p className="mt-1">Checking eligibility…</p>
                  : visibleMissing.length === 0
                    ? <p className="mt-1">Eligible for courier lookup</p>
                    : <ul className="mt-1 list-disc space-y-0.5 pl-5">{visibleMissing.map(requirement => <li key={requirement}>{requirement}</li>)}</ul>}
              </div>
              {courierError && <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{courierError}</div>}
              {courierWarnings.map(warning => <div key={warning} className="rounded-lg bg-amber-50 px-3 py-2 text-sm text-amber-700">{warning}</div>)}
              {selectedCourier?.provider === 'delhivery' && !selectedCourier.booking_supported && <p className="text-xs text-amber-700">Direct Delhivery booking is unavailable because the provider is not configured or this destination is not serviceable.</p>}
              {courierLoading && <p className="text-sm text-slate-500">Loading courier options…</p>}
              {courierOptions.length > 0 && (
                <div className="space-y-2">
                  {courierOptions.map(option => {
                    const selected = option.courier_id === selectedCourierId
                    return (
                      <button key={`${option.courier_name}-${option.courier_id}`} onClick={() => void onSelectCourier(option)} className={`w-full rounded-xl border p-3 text-left transition ${selected ? 'border-[#ff6b35] bg-orange-50/60' : 'border-slate-200 bg-white hover:bg-slate-50'}`}>
                        <div className="flex items-start justify-between gap-3">
                          <div>
                            <div className="flex items-center gap-2">
                              <p className="text-sm font-semibold text-slate-800">{option.courier_name}</p>
                              <span className="rounded-full bg-slate-100 px-2 py-0.5 text-[10px] font-bold uppercase text-slate-500">{option.provider}</span>
                              {selected && <span className="rounded-full bg-[#ff6b35] px-2 py-0.5 text-[10px] font-bold text-white">Selected</span>}
                            </div>
                            <p className="mt-1 text-xs text-slate-500">{option.mode || 'mode n/a'} · {option.estimated_delivery_days ?? '—'} days · ETA {option.expected_delivery_date || '—'}</p>
                            <p className="mt-1 text-[11px] text-slate-400">{option.rate_note}</p>
                          </div>
                          <div className="text-right text-xs text-slate-500">
                            <p>Freight {formatMoney(option.rate)}</p>
                            <p>COD {option.cod_charge == null ? '—' : formatMoney(option.cod_charge)}</p>
                            <p className="font-semibold text-slate-700">Total {formatMoney(option.total_estimated_shipping_cost)}</p>
                            <p>Rating {option.rating == null ? '—' : option.rating.toFixed(2)}</p>
                          </div>
                        </div>
                      </button>
                    )
                  })}
                </div>
              )}
              {shipment && (
                <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                  <p className="font-semibold">Provider: {shipment.provider || 'Shiprocket'}</p>
                  <p>Booking status: {shipment.booking_status || '—'}</p>
                  <p>Courier: {shipment.courier_name || '—'}</p>
                  <p>AWB: {shipment.awb || '—'}</p>
                  <p>Shipment ID: {shipment.shipment_id || '—'}</p>
                  <p>Booked at: {shipment.booked_at ? formatDateTime(shipment.booked_at) : '—'}</p>
                  <p>Latest status: {shipment.latest_status || '—'}</p>
                  {(shipment.provider === 'shiprocket' || shipment.provider === 'delhivery') && shipment.shipment_id && (
                    <button onClick={onRefreshShipment} disabled={shipmentRefreshLoading} className="mt-2 rounded-md border border-emerald-200 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-800 disabled:opacity-60">
                      {shipmentRefreshLoading ? 'Refreshing…' : 'Refresh Shipment Status'}
                    </button>
                  )}
                </div>
              )}
              {courierOptions.length === 0 && <p className="text-xs text-slate-500">{courierSyncMessage}</p>}
            </div>
          </Section>

          {shipment?.awb && (
            <Section title="Shopify Fulfillment">
              <div className="space-y-2 text-sm text-slate-600">
                <p className="font-semibold text-slate-800">
                  {shipment.shopify_fulfillment_sync_status === 'synced' && 'Synced'}
                  {shipment.shopify_fulfillment_sync_status === 'failed' && 'Sync Failed'}
                  {shipment.shopify_fulfillment_sync_status === 'not_applicable' && 'Already Fulfilled / Not Applicable'}
                  {(!shipment.shopify_fulfillment_sync_status || shipment.shopify_fulfillment_sync_status === 'pending') && 'Sync Pending'}
                </p>
                {shipment.shopify_fulfillment_id && <p>Shopify fulfillment: {shipment.shopify_fulfillment_id}</p>}
                {shipment.shopify_fulfillment_status && <p>Shopify status: {shipment.shopify_fulfillment_status}</p>}
                <p>Tracking number: {shipment.shopify_tracking_number || shipment.awb}</p>
                {shipment.shopify_tracking_url && <a className="font-medium text-blue-600 hover:underline" href={shipment.shopify_tracking_url} target="_blank" rel="noreferrer">Open Shopify tracking</a>}
                {shipment.shopify_fulfillment_synced_at && <p>Synced at: {formatDateTime(shipment.shopify_fulfillment_synced_at)}</p>}
                {shipment.shopify_customer_notified != null && <p>Customer notified: {shipment.shopify_customer_notified ? 'Yes' : 'No'}</p>}
                {shipment.shopify_fulfillment_sync_error && <p className="rounded-lg bg-rose-50 px-3 py-2 text-rose-700">{shipment.shopify_fulfillment_sync_error}</p>}
                {shipment.shopify_fulfillment_sync_status !== 'synced' && shipment.shopify_fulfillment_sync_status !== 'not_applicable' && (
                  <button disabled={shopifySyncLoading} onClick={onSyncShopifyFulfillment} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-700 disabled:opacity-60">
                    {shopifySyncLoading ? 'Syncing…' : shipment.shopify_fulfillment_sync_status === 'failed' ? 'Retry Shopify Sync' : 'Sync Shopify Fulfillment'}
                  </button>
                )}
              </div>
            </Section>
          )}

          <Section title="Payment Breakup">
            <details>
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">Collapsed by default</summary>
              <div className="mt-3 space-y-2 text-sm text-slate-500">
                <Line label="Order amount" value={formatMoney(order.amount)} />
                <Line label="Amount paid" value={formatMoney(order.paidAmount)} />
                <Line label="Balance COD" value={formatMoney(order.codCollectableAmount)} />
                <Line label="Shipping amount" value={shipping} />
                <Line label="Payment status" value={order.payment} />
                <Line label="Fulfillment status" value={order.fulfillmentStatus || '—'} />
              </div>
            </details>
          </Section>

          <Section title="Timeline">
            <details>
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">Collapsed by default</summary>
              <ol className="mt-3 ml-2 border-l border-slate-200">
                {['Order Created', 'Payment Received', 'Packed', 'Ready for Dispatch'].map((event, index) => (
                  <li key={event} className="relative pb-5 pl-5 last:pb-0">
                    <span className={`absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-full ${index < 2 ? 'bg-[#ff6b35]' : 'bg-slate-300'}`} />
                    <p className="text-sm font-medium text-slate-700">{event}</p>
                    <p className="mt-0.5 text-xs text-slate-400">{index < 2 ? formatDate(order.createdAt) : 'Awaiting update'}</p>
                  </li>
                ))}
              </ol>
            </details>
          </Section>
        </div>

        <footer className="absolute inset-x-0 bottom-0 flex items-center gap-2 border-t border-slate-200 bg-white px-4 py-3 shadow-[0_-8px_20px_rgba(15,23,42,.05)]">
          {shipment?.awb ? (
            <>
              {(shipment.provider === 'shiprocket' || shipment.provider === 'delhivery') ? (
                <button disabled={labelLoading} onClick={onDownloadLabel} className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-60">
                  <Icon name="truck" size={16} />
                  {labelLoading ? 'Fetching Delhivery label…' : shipment.provider === 'delhivery' ? 'Download Official PDF' : 'Download Label PDF'}
                </button>
              ) : <div className="flex flex-1 items-center justify-center rounded-lg bg-slate-100 px-3 py-2.5 text-sm font-semibold text-slate-500">Official provider PDF label unavailable</div>}
              {shipment.provider === 'delhivery' && <button disabled={labelLoading} onClick={onPrintLabel} className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700 disabled:opacity-60">Open / Print Official PDF</button>}
              <button onClick={() => window.open(shipment.tracking_url || `http://127.0.0.1:8000/api/v1/couriers/shiprocket/orders/${order.internalId}/tracking`, '_blank', 'noopener,noreferrer')} className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700">Open Tracking</button>
            </>
          ) : (
            <button
              disabled={!canBookShipment}
              onClick={() => void onBookShipment(packageNumbers)}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
            >
              <Icon name="truck" size={16} />
              {bookingLoading ? (selectedCourier?.provider === 'delhivery' ? 'Booking with Delhivery…' : 'Booking…') : selectedCourier?.provider === 'shadowfax' ? 'Shadowfax booking is manual' : selectedCourierId ? 'Book Shipment' : 'Select a courier above'}
            </button>
          )}
          <button onClick={onClose} className="rounded-lg px-2 py-2.5 text-sm font-semibold text-slate-500 hover:bg-slate-50">Close</button>
        </footer>
      </aside>
    </div>
  )
})

function Field({ label, value, onChange, testId }: { label: string; value: string; onChange: (value: string) => void; testId?: string }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</span>
      <input data-testid={testId} value={value} onChange={e => onChange(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-orange-300 focus:ring-2 focus:ring-orange-100" />
    </label>
  )
}

function KeyValue({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-slate-50 px-3 py-2">
      <p className="text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</p>
      <p className="mt-1 text-sm font-semibold text-slate-700">{value}</p>
    </div>
  )
}

function Line({ label, value }: { label: string; value: string }) {
  return <div className="flex justify-between text-slate-600"><span>{label}</span><span className="font-medium">{value}</span></div>
}

function Section({ title, children }: { title: string; children: ReactNode }) {
  return <section className="border-b border-slate-100 px-5 py-5"><h3 className="mb-4 text-sm font-bold text-slate-800">{title}</h3>{children}</section>
}

export default App
