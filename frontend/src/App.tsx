import type { ReactNode } from 'react'
import { memo, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  addOrderCallLog,
  recordCodWhatsAppOpened,
  saveManualShadowfaxShipment,
  testShadowfaxDirect324541,
  getShadowfaxDirect324541Status,
  resetShadowfaxDirect324541,
  type ShadowfaxDirectTestState,
  addAddressConfirmationComment,
  cancelOrder,
  apiBase,
  bookShiprocketShipment,
  checkShiprocketCouriers,
  formatMoney,
  getBookingEligibility,
  getOrderOperations,
  getCancellationPreflight,
  getOrders,
  createLabelBatch,
  confirmLabelBatch,
  exportOrders,
  getLabelQueue,
  getShiprocketCleanupPending,
  getOrdersReconciliation,
  cancelShiprocketOnly,
  verifyShiprocketOnlyCancellation,
  shiprocketCancellationMessage,
  shouldRemoveCleanupRecord,
  reconciliationFilterLabel,
  selectReconciliationFilter,
  clearReconciliationFilter,
  reconciliationDataset,
  mapApiOrder,
  getActiveLabelBatches,
  labelBatchPdfUrl,
  requestLabelReprint,
  retryShiprocketCleanup,
  refreshShiprocketShipment,
  reconcileCourierBooking,
  cancelCourierShipment,
  saveAndVerifyOrderAddress,
  saveOrderPackage,
  selectShiprocketCourier,
  shippingLabelUrl,
  syncShopifyFulfillment,
  type Order,
  type OrderOperations,
  type RiskLevel,
  type CancellationPreflight,
  type OrderCounts,
  type ShiprocketCleanupRecord,
  type ShiprocketCancellationResult,
  type OrdersReconciliationSummary,
  type ReconciliationFilter,
  type ReconciliationRecord,
} from './services/orders'
import { logout } from './services/auth'
import { useAuth } from './auth-context'
import { UsersPage } from './components/UsersPage'
import { NDRPage } from './components/NDRPage'
import { DashboardPage } from './components/DashboardPage'
import { AnalyticsPage } from './components/AnalyticsPage'
import { formatDateTime } from './utils/time'
import { orderContactSectionTitle } from './utils/operations'
import { EngageCircle, EngageProgress } from './components/EngageStatus'
import { OrderStatusBadge } from './components/OrderStatusBadge'
import { engageCategory } from './utils/engage'
import { hasShipmentEvidence, listStatus, type OperationalStatus } from './utils/orderStatus'
import { displayedOrderNumber, orderNumberClipboardValue, stopCopyPropagation } from './utils/orderNumber'

type IconName = 'grid' | 'bag' | 'alert' | 'users' | 'chart' | 'settings' | 'search' | 'bell' | 'filter' | 'chevron' | 'more' | 'eye' | 'truck' | 'calendar' | 'close' | 'copy' | 'phone' | 'external' | 'repeat' | 'tag' | 'edit' | 'call'
type TabKey = 'fresh' | 'previous' | 'all' | 'labels_to_print' | 'awaiting_confirmation' | 'printed_today' | 'shiprocket_cleanup'
export type CallResult = 'No Answer' | 'Busy' | 'Switched Off' | 'On Hold' | 'Confirmed' | 'Cancelled'
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

const navItems = ['Dashboard', 'Analytics', 'Orders', 'NDR', 'Reconciliation', 'Settings'] as const
export const workspaceLoadsForPage = (page: typeof navItems[number]) => ({
  orders: page === 'Orders',
  reconciliation: page === 'Reconciliation',
})
const tabItems: { key: TabKey; label: string }[] = [
  { key: 'fresh', label: 'Fresh Orders' },
  { key: 'previous', label: 'Previous Pending Orders' },
]
const dispatchItems: { key: TabKey; label: string }[] = [
  { key: 'labels_to_print', label: 'Labels to Print' },
  { key: 'printed_today', label: 'Printed Today' },
]
export const callResults: CallResult[] = ['Confirmed', 'No Answer', 'Busy', 'Switched Off', 'On Hold', 'Cancelled']
export const callResultLabel = (result: CallResult) => result === 'Cancelled' ? 'Cancel' : result
export const COD_WHATSAPP_MESSAGE = `Hello! We tried calling you to confirm your Mumchies COD order but couldnt connect.\n\nPlease reply CONFIRM if you would like to confirm your order and will be available to receive and pay for the order at the time of delivery.\n\nWe will dispatch the order after receiving your confirmation.\n\n Team Mumchies`
export function indianWhatsAppNumber(value: string | null | undefined): string | null {
  let digits = String(value || '').replace(/\D/g, '')
  if (digits.length === 11 && digits.startsWith('0')) digits = digits.slice(1)
  if (digits.length === 10 && /^[6-9]/.test(digits)) return `91${digits}`
  if (digits.length === 12 && digits.startsWith('91') && /^[6-9]/.test(digits.slice(2))) return digits
  return null
}
export function shouldShowCodWhatsApp(paymentType: string, latestResult: string | null | undefined): boolean {
  return paymentType !== 'prepaid' && ['No Answer', 'Busy', 'Switched Off'].includes(latestResult || '')
}
export function codWhatsAppUrl(value: string | null | undefined): string | null {
  const phone = indianWhatsAppNumber(value)
  return phone ? `https://wa.me/${phone}?text=${encodeURIComponent(COD_WHATSAPP_MESSAGE)}` : null
}
const reconciliationDate = (value: string | null) => {
  if (!value) return '—'
  const parsed = new Date(value)
  return Number.isNaN(parsed.getTime()) ? value : formatDateTime(value)
}
const reconciliationRecordToOrder = (record: ReconciliationRecord): Order => {
  if (record.order) return mapApiOrder(record.order)
  const paymentType = record.payment_type === 'cod' || record.payment_type === 'partial_cod' ? record.payment_type : 'prepaid'
  const createdAt = record.created_date && !Number.isNaN(new Date(record.created_date).getTime()) ? record.created_date : new Date(0).toISOString()
  return {
    internalId: record.order_id, orderNumber: record.order_number, shopifyName: null, createdAt, createdDate: reconciliationDate(record.created_date),
    customerName: record.customer_name || 'Shiprocket customer', amount: record.total_amount, shippingAmount: null,
    payment: paymentType === 'cod' ? 'COD' : paymentType === 'partial_cod' ? 'Partial COD' : 'Prepaid', orderTotal: record.total_amount,
    paidAmount: 0, outstandingAmount: 0, codCollectableAmount: 0, paymentType, financialStatus: null,
    risk: ['High', 'Medium'].includes(record.risk) ? record.risk as RiskLevel : 'Low', fulfillmentStatus: null, shopifyStatus: null,
    cancelledAt: null, customerId: null, customerOrdersCount: null, phone: null, email: null, shippingAddress: null, products: [], tags: [],
    firstActionAt: null, humanActionCount: 0, callAttemptCount: 0, latestCallResult: null, operationalStatus: record.status,
    addressVerified: false, addressVerifiedAt: null, addressVerifiedBy: null, verifiedAddressSnapshot: null, correctedAddress: null,
    courierSyncStatus: null, courierSyncError: null, addressSyncResults: null, packageDetails: null, selectedCourier: null, shipment: null, externalTracking: null,
    engageOrderId: null, orderConfirmation: null, orderConfirmationMessage: null, addressConfirmation: null,
    addressConfirmationMessage: null, codToPrepaid: null, codToPrepaidMessage: null, engageLastSyncedAt: null,
  }
}
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

function CopyButton({ value, label, stopPropagation = false }: { value: string; label: 'order number' | 'phone number'; stopPropagation?: boolean }) {
  const [feedback, setFeedback] = useState('')
  const title = `Copy ${label}`
  const copy = async (event: React.MouseEvent<HTMLButtonElement>) => {
    stopCopyPropagation(event, stopPropagation)
    try {
      await navigator.clipboard.writeText(value)
      setFeedback('Copied')
    } catch {
      setFeedback('Copy failed')
    }
    window.setTimeout(() => setFeedback(''), 1500)
  }
  return <span className="inline-flex items-center gap-1"><button type="button" aria-label={title} title={title} onClick={copy} className="rounded p-1 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Icon name="copy" size={14} /></button>{feedback && <span role="status" className="text-[10px] font-medium text-slate-500">{feedback}</span>}</span>
}

const formatDate = (value: string) => new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric' }).format(new Date(value))
const formatOrderDateTime = (value: string) => {
  const date = new Date(value)
  return {
    date: new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', timeZone: 'Asia/Kolkata' }).format(date),
    time: new Intl.DateTimeFormat('en-IN', { hour: '2-digit', minute: '2-digit', hour12: false, timeZone: 'Asia/Kolkata' }).format(date),
  }
}
function App() {
  const authUser = useAuth()
  const [activePage, setActivePage] = useState<typeof navItems[number]>('Dashboard')
  const [orders, setOrders] = useState<Order[]>([])
  const [selectedOrderId, setSelectedOrderId] = useState<string | null>(null)
  const [selectedOrderSnapshot, setSelectedOrderSnapshot] = useState<Order | null>(null)
  const [operations, setOperations] = useState<OrderOperations | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [queue, setQueue] = useState<TabKey>('fresh')
  const [searchDraft, setSearchDraft] = useState('')
  const [search, setSearch] = useState('')
  const [attemptFilter, setAttemptFilter] = useState<'1' | '2' | '3' | '4_plus' | null>(null)
  const [pendingView, setPendingView] = useState<'follow_up' | 'on_hold'>('follow_up')
  const [payment, setPayment] = useState('All')
  const [risk, setRisk] = useState('All')
  const [sort, setSort] = useState('Newest first')
  const [page, setPage] = useState(1)
  const [pageSize, setPageSize] = useState<20 | 50 | 100>(20)
  const [total, setTotal] = useState(0)
  const [totalPages, setTotalPages] = useState(1)
  const [counts, setCounts] = useState<OrderCounts>({ operations: 0, fresh: 0, previous: 0, follow_up: 0, on_hold: 0, all: 0, labels_to_print: 0, awaiting_confirmation: 0, printed_today: 0, new_orders: 0, cod: 0, prepaid: 0, high_risk: 0, repeat_customers: 0, cod_collectable: 0, prepaid_value: 0, awaiting_order_confirmation: 0, awaiting_address_verification: 0, cod_conversion_pending: 0 })
  const [cleanupRecords, setCleanupRecords] = useState<ShiprocketCleanupRecord[]>([])
  const [cleanupResults, setCleanupResults] = useState<Record<string, ShiprocketCancellationResult>>({})
  const [reconciliation, setReconciliation] = useState<OrdersReconciliationSummary | null>(null)
  const [reconciliationError, setReconciliationError] = useState('')
  const [reconciliationRetry, setReconciliationRetry] = useState(0)
  const [reconciliationFilter, setReconciliationFilter] = useState<ReconciliationFilter | null>(null)
  const searchRef = useRef<HTMLInputElement>(null)
  const [notice, setNotice] = useState('')
  const [repeatIds, setRepeatIds] = useState<Set<string>>(new Set())
  const [callResult, setCallResult] = useState<CallResult>('No Answer')
  const [callComment, setCallComment] = useState('')
  const [cancellationPreflight, setCancellationPreflight] = useState<CancellationPreflight | null>(null)
  const [cancellationLoading, setCancellationLoading] = useState(false)
  const [cancellationResult, setCancellationResult] = useState<Record<string, { status: string; error?: string }> | null>(null)
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
  const [shadowfaxTestState, setShadowfaxTestState] = useState<ShadowfaxDirectTestState | null>(null)
  const bookingRequestInFlight = useRef(false)
  const courierRequestOrderRef = useRef<string | null>(null)
  const drawerGenerationRef = useRef(0)
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
  const [labelQueue, setLabelQueue] = useState<{ labels_to_print: NonNullable<Order['shipment']>[]; awaiting_confirmation: NonNullable<Order['shipment']>[]; printed_today: NonNullable<Order['shipment']>[] }>({ labels_to_print: [], awaiting_confirmation: [], printed_today: [] })
  const [showLabels, setShowLabels] = useState(false)
  const [labelSearch, setLabelSearch] = useState('')
  const labelSearchRef = useRef<HTMLInputElement>(null)
  const [selectedLabels, setSelectedLabels] = useState<Set<string>>(new Set())
  const [activeBatch, setActiveBatch] = useState<{ id: string; order_ids: string[] } | null>(null)
  const [printedLabels, setPrintedLabels] = useState<Set<string>>(new Set())
  const refreshLabels = useCallback(() => void getLabelQueue().then(setLabelQueue).catch(() => undefined), [])
  const refreshCleanup = useCallback(() => void getShiprocketCleanupPending().then(result => setCleanupRecords(result.items)).catch(() => undefined), [])
  const loadOrders = useCallback(async (signal?: AbortSignal) => {
    try {
      setLoading(true)
      setError('')
      if (queue === 'shiprocket_cleanup') {
        const cleanup = await getShiprocketCleanupPending()
        setCleanupRecords(cleanup.items)
        setOrders([])
        setTotal(cleanup.total)
        setTotalPages(1)
        return
      }
      const data = await getOrders({
        page,
        pageSize,
        queue,
        search,
        payment: payment === 'All' ? 'all' : payment.toLowerCase(),
        risk: risk === 'All' ? 'all' : risk.toLowerCase(),
        sort: { 'Newest first': 'newest', 'Oldest first': 'oldest', 'COD first': 'cod_first', 'Prepaid first': 'prepaid_first', 'Value high to low': 'value_desc', 'Value low to high': 'value_asc' }[sort] || 'newest',
        attempt: queue === 'previous' ? attemptFilter ?? 'all' : 'all',
        pendingView: queue === 'previous' ? pendingView : 'follow_up',
      }, signal)
      setOrders(data.items)
      setTotal(data.total)
      setTotalPages(data.totalPages)
      setCounts(data.counts)
      if (data.page !== page) setPage(data.page)
      const counts = new Map<string, number>()
      const repeat = new Set<string>()
      for (const order of data.items) {
        if ((order.customerOrdersCount || 0) > 1) repeat.add(order.internalId)
        if (order.customerId) {
          const next = (counts.get(order.customerId) || 0) + 1
          counts.set(order.customerId, next)
          if (next > 1) repeat.add(order.internalId)
        }
      }
      setRepeatIds(repeat)
      setSelectedOrderSnapshot(current => {
        if (!selectedOrderId) return null
        return data.items.find(order => order.internalId === selectedOrderId) || current
      })
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError((err as Error).message)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [attemptFilter, page, pageSize, payment, pendingView, queue, risk, search, selectedOrderId, sort])

  useEffect(() => {
    const timeout = window.setTimeout(() => { setSearch(searchDraft.trim()); setPage(1) }, 350)
    return () => window.clearTimeout(timeout)
  }, [searchDraft])

  const refreshReconciliation = useCallback((refresh = false) => {
    setReconciliationError('')
    void getOrdersReconciliation(refresh).then(setReconciliation).catch(error => {
      const message = (error as Error).message
      setReconciliationError(message)
      if (message.includes('preparing')) window.setTimeout(() => setReconciliationRetry(value => value + 1), 3_000)
    })
  }, [])

  useEffect(() => {
    if (!workspaceLoadsForPage(activePage).orders) return
    const controller = new AbortController()
    const timeout = window.setTimeout(() => void loadOrders(controller.signal), 0)
    return () => {
      controller.abort()
      window.clearTimeout(timeout)
    }
  }, [activePage, loadOrders])

  useEffect(() => {
    const loads = workspaceLoadsForPage(activePage)
    if (loads.orders) { refreshLabels(); refreshCleanup() }
    if (loads.reconciliation) {
      const timeout = window.setTimeout(() => refreshReconciliation(false), 0)
      return () => window.clearTimeout(timeout)
    }
  }, [activePage, reconciliationRetry, refreshCleanup, refreshLabels, refreshReconciliation])

  useEffect(() => {
    if (activePage !== 'Reconciliation' || !reconciliation?.refreshing) return
    const timeout = window.setTimeout(() => refreshReconciliation(false), 5_000)
    return () => window.clearTimeout(timeout)
  }, [activePage, reconciliation?.refreshing, refreshReconciliation])

  useEffect(() => {
    if (!workspaceLoadsForPage(activePage).orders || selectedOrderId) return
    const interval = window.setInterval(() => void loadOrders(), 60_000)
    return () => window.clearInterval(interval)
  }, [activePage, loadOrders, selectedOrderId])

  useEffect(() => {
    if (!notice) return
    const timeout = window.setTimeout(() => setNotice(''), 3_000)
    return () => window.clearTimeout(timeout)
  }, [notice])

  const reconciliationRows = useMemo(() => reconciliationDataset(reconciliation, reconciliationFilter), [reconciliation, reconciliationFilter])
  const reconciliationOrders = useMemo(() => reconciliationRows.map(reconciliationRecordToOrder), [reconciliationRows])
  const selectedOrder = useMemo(() => [...orders, ...reconciliationOrders].find(order => order.internalId === selectedOrderId) || (selectedOrderSnapshot?.internalId === selectedOrderId ? selectedOrderSnapshot : null), [orders, reconciliationOrders, selectedOrderId, selectedOrderSnapshot])
  useEffect(() => {
    if (selectedOrder?.orderNumber === '324541' && ['owner', 'admin'].includes(authUser?.role || '')) {
      void getShadowfaxDirect324541Status().then(setShadowfaxTestState).catch(() => setShadowfaxTestState(null))
    }
  }, [selectedOrder?.orderNumber, authUser?.role])

  const applyCanonicalShipment = (orderId: string, shipment: Order['shipment']) => {
    if (!shipment) return
    const update = (order: Order) => JSON.stringify(order.shipment) === JSON.stringify(shipment) ? order : { ...order, shipment }
    setOrders(previous => previous.map(order => order.internalId === orderId ? update(order) : order))
    setSelectedOrderSnapshot(previous => previous?.internalId === orderId ? update(previous) : previous)
  }

  useEffect(() => {
    if (!selectedOrder) return
    let active = true
    void (async () => {
      setBookingEligibility(null)
      setOperations(null)
      setCourierOptions([])
      setCourierWarnings([])
      setSelectedCourierId(null)
      setCourierError('')
      setCancellationPreflight(null)
      const ops = await getOrderOperations(selectedOrder.internalId)
      if (!active) return
      setOperations(ops)
      applyCanonicalShipment(selectedOrder.internalId, ops.shipment)
      setCallResult('No Answer')
      setCallComment('')
      setAddressDraft({
        customer_name: ops.corrected_address?.customer_name ?? selectedOrder.shippingAddress?.name ?? selectedOrder.customerName ?? '',
        phone: ops.corrected_address?.phone ?? selectedOrder.shippingAddress?.phone ?? selectedOrder.phone ?? '',
        address_line1: ops.corrected_address?.address_line1 ?? selectedOrder.shippingAddress?.addressLine1 ?? selectedOrder.shippingAddress?.address ?? '',
        address_line2: ops.corrected_address?.address_line2 ?? selectedOrder.shippingAddress?.addressLine2 ?? '',
        landmark: ops.corrected_address?.landmark ?? selectedOrder.shippingAddress?.landmark ?? '',
        city: ops.corrected_address?.city ?? selectedOrder.shippingAddress?.city ?? '',
        state: ops.corrected_address?.state ?? selectedOrder.shippingAddress?.state ?? '',
        pincode: ops.corrected_address?.pincode ?? selectedOrder.shippingAddress?.pincode ?? '',
      })
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
    drawerGenerationRef.current += 1
    courierRequestOrderRef.current = null
    setBookingEligibility(null)
    setOperations(null)
    setCourierOptions([])
    setCourierWarnings([])
    setSelectedCourierId(null)
    setCourierError('')
    setCourierLoading(false)
    setCancellationPreflight(null)
    setSelectedOrderSnapshot([...orders, ...reconciliationOrders].find(order => order.internalId === orderId) || null)
    setSelectedOrderId(orderId)
  }

  const handleCleanupResult = (record: ShiprocketCleanupRecord, result: ShiprocketCancellationResult) => {
    setCleanupResults(previous => ({ ...previous, [record.shiprocket_order_id]: result }))
    setNotice(shiprocketCancellationMessage(result))
    if (shouldRemoveCleanupRecord(result)) {
      setCleanupRecords(previous => previous.filter(value => value.shiprocket_order_id !== record.shiprocket_order_id))
    }
  }

  const sendShiprocketCleanup = (record: ShiprocketCleanupRecord) => {
    if (!window.confirm(`Cancel only Shiprocket order ${record.order_number}? Shopify will not be cancelled.`)) return
    void cancelShiprocketOnly(record).then(result => handleCleanupResult(record, result)).catch(error => setNotice(error.message))
  }

  const verifyShiprocketCleanup = (record: ShiprocketCleanupRecord) => {
    void verifyShiprocketOnlyCancellation(record).then(result => handleCleanupResult(record, result)).catch(error => setNotice(error.message))
  }

  const displayedOrders = orders

  const summaryCounts = useMemo(() => ({
    fresh: counts.fresh,
    previous: counts.previous,
    all: counts.all,
    labels_to_print: counts.labels_to_print,
    awaiting_confirmation: counts.awaiting_confirmation,
    printed_today: counts.printed_today,
    shiprocket_cleanup: cleanupRecords.length,
  }), [cleanupRecords.length, counts])

  const statusFromOrder = (order: Order): OperationalStatus => {
    return listStatus(order)
  }

  const callLog = [...(operations?.call_logs || [])].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
  const courierSyncMessage = operations?.courier_sync_error || ''
  const status = selectedOrder ? statusFromOrder(selectedOrder) : 'Call Pending'
  const isRepeat = selectedOrder ? repeatIds.has(selectedOrder.internalId) : false
  const visibleCount = search ? total : counts.operations
  const addressVerifiedLabel = operations?.address_verified
    ? `Address Verified by ${operations.address_verified_by || 'operator'} on ${operations.address_verified_at ? formatDateTime(operations.address_verified_at) : 'unknown time'}`
    : 'Address Verification Pending'

  const refreshEligibility = async (orderId: string) => {
    const eligibility = await getBookingEligibility(orderId)
    setBookingEligibility(eligibility)
  }

  const saveCallLog = async () => {
    if (!selectedOrder) return
    if (callResult === 'On Hold' && callComment.trim().length < 3) {
      setNotice('Add a reason before placing the order On Hold.')
      return
    }
    if (callResult === 'Cancelled') {
      try {
        setCancellationPreflight(await getCancellationPreflight(selectedOrder.internalId))
      } catch (err) { setNotice((err as Error).message) }
      return
    }
    try {
      setCourierOptions([])
      setCourierWarnings([])
      setSelectedCourierId(null)
      setCourierError('')
      setBookingEligibility(null)
      const updated = await addOrderCallLog(selectedOrder.internalId, {
        result: callResult,
        comment: callComment,
      })
      setOperations(updated)
      // A call log can only move a not-yet-shipped order between local operational states. An
      // order that already has an existing shipment/fulfilment must never be downgraded back to
      // "Ready for Booking" (or any other local state) by a call outcome - see Part 2/3 of the
      // 2026-07-21 shipment-state regression fix.
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, latestCallResult: updated.call_logs?.[0]?.result || null, operationalStatus: (hasShipmentEvidence(order) ? order.operationalStatus : (updated.call_logs?.[0]?.result === 'Callback Requested' ? 'Callback Required' : updated.call_logs?.[0]?.result === 'Confirmed' ? (order.payment === 'Prepaid' && !updated.address_verified ? 'Address Verification Pending' : 'Ready for Booking') : updated.call_logs?.[0]?.result === 'Wrong Number' ? 'Needs Review' : updated.call_logs?.[0]?.result === 'Cancelled' ? 'Cancelled' : 'Call Pending')) as OperationalStatus | null, addressVerified: updated.address_verified, addressVerifiedAt: updated.address_verified_at, addressVerifiedBy: updated.address_verified_by, verifiedAddressSnapshot: updated.verified_address_snapshot, correctedAddress: updated.corrected_address, courierSyncStatus: updated.courier_sync_status, courierSyncError: updated.courier_sync_error } : order))
      setCallComment('')
      const [freshOperations, freshEligibility] = await Promise.all([
        getOrderOperations(selectedOrder.internalId),
        getBookingEligibility(selectedOrder.internalId),
      ])
      setOperations(freshOperations)
      setBookingEligibility(freshEligibility)
      await loadOrders()
      setNotice('Call attempt saved')
    } catch (err) {
      setNotice((err as Error).message)
    }
  }

  const saveAddressConfirmation = async () => {
    if (!selectedOrder) return
    try {
      const updated = await addAddressConfirmationComment(selectedOrder.internalId, callComment)
      setOperations(updated)
      setCallComment('')
      setNotice('Address confirmation comment saved')
    } catch (err) { setNotice((err as Error).message) }
  }

  const saveAndVerifyAddress = async () => {
    if (!selectedOrder) return
    try {
      const result = await saveAndVerifyOrderAddress(selectedOrder.internalId, addressDraft)
      setOperations(result.operations)
      setOrders(previous => previous.map(order => order.internalId === selectedOrder.internalId ? { ...order, correctedAddress: result.operations.corrected_address, addressVerified: result.operations.address_verified, addressVerifiedAt: result.operations.address_verified_at, addressVerifiedBy: result.operations.address_verified_by, verifiedAddressSnapshot: result.operations.verified_address_snapshot, addressSyncResults: result.operations.address_sync_results } : order))
      const [freshOperations, freshEligibility] = await Promise.all([
        getOrderOperations(selectedOrder.internalId),
        getBookingEligibility(selectedOrder.internalId),
      ])
      setOperations(freshOperations)
      setBookingEligibility(freshEligibility)
      await loadOrders()
      setNotice(result.verified ? (result.validation.warnings.length ? `Address verified with advisories: ${result.validation.warnings.join('; ')}` : 'Address saved and verified') : `Address saved but not verified: ${result.validation.blockers.join('; ')}`)
      return result
    } catch (err) { setNotice((err as Error).message) }
  }


  const checkCouriers = async (packageNumbers: { weight_kg: number; length_cm: number | null; breadth_cm: number | null; height_cm: number | null }) => {
    if (!selectedOrder || !Number.isFinite(packageNumbers.weight_kg) || packageNumbers.weight_kg <= 0) return
    const orderId = selectedOrder.internalId
    const generation = drawerGenerationRef.current
    if (courierRequestOrderRef.current === orderId) return
    courierRequestOrderRef.current = orderId
    setCourierLoading(true)
    setCourierError('')
    setCourierWarnings([])
    setCourierOptions([])
    try {
      await saveOrderPackage(orderId, packageNumbers)
      const result = await checkShiprocketCouriers(orderId, {
        ...packageNumbers,
        courier_payment_mode: selectedOrder.payment,
      })
      if (generation !== drawerGenerationRef.current) return
      const sorted = [...(result.couriers ?? [])].sort((a, b) => a.total_estimated_shipping_cost - b.total_estimated_shipping_cost)
      setCourierOptions(sorted)
      setCourierWarnings(result.provider_warnings ?? [])
      if (sorted.length === 0) setCourierError('No courier services are currently available. Check the package and address, then retry.')
      if (selectedCourierId && !sorted.some(courier => courier.courier_id === selectedCourierId)) {
        setSelectedCourierId(null)
      }
      await refreshEligibility(orderId)
      setNotice('Courier options loaded')
    } catch (err) {
      if (generation !== drawerGenerationRef.current) return
      setCourierError((err as Error).message)
    } finally {
      if (courierRequestOrderRef.current === orderId) courierRequestOrderRef.current = null
      if (generation === drawerGenerationRef.current) setCourierLoading(false)
    }
  }

  const selectCourier = async (courier: CourierQuote) => {
    if (!selectedOrder || !courier.courier_id) return
    setCourierError('')
    try {
      const result = await selectShiprocketCourier(selectedOrder.internalId, { ...courier, courier_id: courier.courier_id })
      setSelectedCourierId(result.selected_courier?.courier_id ?? courier.courier_id)
      setOperations(prev => prev ? { ...prev, selected_courier: result.selected_courier } : prev)
      await refreshEligibility(selectedOrder.internalId)
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
      const reopened = await getOrderOperations(selectedOrder.internalId)
      setOperations(reopened)
      applyCanonicalShipment(selectedOrder.internalId, reopened.shipment ?? result.shipment ?? null)
      if (result.warning) setCourierError(`Shiprocket cleanup failed: ${result.warning}`)
      setNotice(result.warning ? 'Delhivery shipment booked; Shiprocket cleanup needs attention' : result.existing ? 'Existing shipment loaded' : 'Shipment booked')
    } catch (err) {
      setCourierError((err as Error).message)
    } finally {
      bookingRequestInFlight.current = false
      setBookingLoading(false)
    }
  }

  const saveManualShadowfax = async (payload: { awb?: string; provider_id?: string; service_name?: string; booked_at?: string; freight?: number; note?: string }) => {
    if (!selectedOrder) return
    setBookingLoading(true); setCourierError('')
    try {
      const result = await saveManualShadowfaxShipment(selectedOrder.internalId, payload)
      const reopened = await getOrderOperations(selectedOrder.internalId)
      setOperations(reopened)
      applyCanonicalShipment(selectedOrder.internalId, reopened.shipment ?? result.shipment ?? null)
      setNotice('Shadowfax manual shipment saved')
    } catch (error) { setCourierError((error as Error).message); throw error } finally { setBookingLoading(false) }
  }

  const testShadowfaxDirect = async () => {
    if (!selectedOrder || selectedOrder.orderNumber !== '324541') return
    if (!window.confirm('Create the one approved live Shadowfax shipment for order #324541? This can be used only once.')) return
    setBookingLoading(true); setCourierError('')
    try {
      const result = await testShadowfaxDirect324541()
      const reopened = await getOrderOperations(selectedOrder.internalId)
      setOperations(reopened)
      applyCanonicalShipment(selectedOrder.internalId, reopened.shipment ?? null)
      setNotice(`Shadowfax booked: ${result.booking.awb || 'AWB returned'}`)
    } catch (error) { setCourierError((error as Error).message) } finally {
      setBookingLoading(false)
      void getShadowfaxDirect324541Status().then(setShadowfaxTestState).catch(() => undefined)
    }
  }

  const resetShadowfaxDirect = async () => {
    if (!selectedOrder || selectedOrder.orderNumber !== '324541') return
    if (!window.confirm('Reset the Shadowfax test attempt for order 324541? Only continue after confirming no shipment exists in Shadowfax.')) return
    setBookingLoading(true); setCourierError('')
    try {
      setShadowfaxTestState(await resetShadowfaxDirect324541())
      setNotice('Shadowfax test attempt reset')
    } catch (error) { setCourierError((error as Error).message) } finally { setBookingLoading(false) }
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

  const reconcileShipment = async () => {
    if (!selectedOrder) return
    setShipmentRefreshLoading(true); setCourierError('')
    try {
      const result = await reconcileCourierBooking(selectedOrder.internalId)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, shipment: result.shipment } : order))
      setOperations(await getOrderOperations(selectedOrder.internalId)); setNotice('Booking reconciliation completed')
    } catch (err) { setCourierError((err as Error).message) } finally { setShipmentRefreshLoading(false) }
  }

  const cancelShipment = async () => {
    if (!selectedOrder || !window.confirm('Cancel this courier shipment only? Shipped and delivered shipments are protected.')) return
    setShipmentRefreshLoading(true); setCourierError('')
    try {
      const result = await cancelCourierShipment(selectedOrder.internalId)
      setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, shipment: result.shipment } : order))
      setOperations(await getOrderOperations(selectedOrder.internalId)); setNotice(result.result.message)
    } catch (err) { setCourierError((err as Error).message) } finally { setShipmentRefreshLoading(false) }
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
            <img src="/mumchies-logo.png" alt="Mumchies" className="h-10 w-auto object-contain" />
            <div>
              <p className="text-xs font-bold uppercase tracking-[.14em] text-slate-400">Mumchies OS</p>
              <h1 className="text-lg font-bold tracking-tight">Operations Console</h1>
            </div>
          </div>
          <nav className="ml-2 hidden flex-1 gap-2 overflow-x-auto md:flex">
            {navItems.filter(item => item !== 'Settings' || authUser?.role === 'owner').map(item => (
              <button key={item} onClick={() => setActivePage(item)} className={`whitespace-nowrap rounded-full px-4 py-2 text-sm font-medium ${item === activePage ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600 hover:bg-slate-200'}`}>{item}</button>
            ))}
          </nav>
          <div className="ml-auto flex items-center gap-2">
            <span className="hidden text-sm font-semibold text-slate-600 lg:inline">{authUser?.display_name}</span>
            <button className="rounded-lg p-2 text-slate-500 hover:bg-slate-100"><Icon name="bell" /></button>
            <button onClick={() => void logout()} className="rounded-lg px-3 py-2 text-sm font-semibold text-slate-600 hover:bg-slate-100">Log out</button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-[1800px] px-4 py-5 lg:px-6">
        {activePage === 'Dashboard' && <DashboardPage onNavigate={target => {
          if (target === 'active_ndr' || target === 'ndr_over_sla') { setActivePage('NDR'); return }
          if (target === 'reconciliation_exceptions') { setActivePage('Reconciliation'); return }
          setActivePage('Orders')
          if (target === 'fresh') setQueue('fresh')
          else if (target === 'follow_up') { setQueue('previous'); setPendingView('follow_up') }
          else if (target === 'on_hold') { setQueue('previous'); setPendingView('on_hold') }
          else setQueue('all')
        }} />}
        {activePage === 'Analytics' && <AnalyticsPage />}
        {activePage === 'Settings' && authUser?.role === 'owner' && <UsersPage />}
        {activePage === 'NDR' && <NDRPage />}
        {activePage === 'Reconciliation' && <div>
          <div className="mb-5"><p className="text-sm font-medium text-[#ff6b35]">Reconciliation</p><h2 className="mt-1 text-2xl font-bold tracking-tight">Order reconciliation</h2></div>
          <div className="mb-5 border-b border-slate-200"><button className="border-b-2 border-slate-900 px-1 pb-3 text-sm font-semibold text-slate-900">OS / Shiprocket Reconciliation</button></div>
          <section className="mb-5 rounded-xl border border-slate-200 bg-white p-4 shadow-sm"><div className="flex flex-wrap items-center justify-between gap-2"><div><p className="text-xs font-bold uppercase tracking-[.12em] text-slate-400">OS / Shiprocket reconciliation</p><p className="mt-1 text-xs text-slate-500">Operational and Shiprocket totals may differ while orders sync or use another courier.</p>{reconciliation?.last_refreshed_at && <p className="mt-1 text-[11px] text-slate-400">Last refreshed {formatDateTime(reconciliation.last_refreshed_at)}{reconciliation.refreshing ? ' · refreshing…' : ''}</p>}{reconciliation?.refresh_error && <p className="mt-1 text-[11px] text-amber-700">{reconciliation.refresh_error}</p>}</div><button onClick={() => refreshReconciliation(true)} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600">Refresh reconciliation</button></div>{reconciliation ? <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">{([
            ['operations', 'Operations Queue', reconciliation.operations_queue],
            ['shiprocket_new', 'Shiprocket New', reconciliation.shiprocket_new],
            ['both', 'Present in Both', reconciliation.present_in_both],
            ['cleanup_pending', 'Cleanup Pending', reconciliation.cleanup_pending],
            ['missing_in_shiprocket', 'Missing in Shiprocket', reconciliation.missing_in_shiprocket],
          ] as [ReconciliationFilter, string, number][]).map(([key, label, value]) => { const active = reconciliationFilter === key; return <button type="button" aria-pressed={active} key={key} onClick={() => setReconciliationFilter(current => selectReconciliationFilter(current, key))} className={`cursor-pointer rounded-lg border px-3 py-2 text-left transition focus:outline-none focus:ring-2 focus:ring-orange-300 ${active ? 'border-orange-300 bg-orange-50 ring-2 ring-orange-100' : 'border-transparent bg-slate-50 hover:border-slate-300 hover:bg-slate-100'}`}><p className="text-[11px] font-semibold text-slate-500">{label}</p><p className="mt-1 text-lg font-bold text-slate-900">{value}</p></button> })}</div> : <p className="mt-3 text-sm text-slate-500">{reconciliationError || 'Reconciliation data is unavailable. Click Refresh to try again.'}</p>}</section>
          {reconciliationFilter && <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm"><div className="flex flex-wrap items-center justify-between gap-3 border-b border-slate-200 px-4 py-4"><div><h3 className="text-lg font-bold text-slate-900">{reconciliationFilterLabel(reconciliationFilter)}</h3><p className="text-sm text-slate-500">{reconciliationRows.length} orders</p></div><button onClick={() => setReconciliationFilter(clearReconciliationFilter())} className="rounded-md border border-slate-200 px-3 py-1.5 text-xs font-semibold text-slate-600 hover:bg-slate-50">Clear Filter</button></div><OrdersTable orders={reconciliationOrders} repeatIds={repeatIds} onOpen={openOrder} reconciliationRows={reconciliationRows} reconciliationFilter={reconciliationFilter} cleanupRecords={cleanupRecords} cleanupResults={cleanupResults} onCleanup={sendShiprocketCleanup} onVerify={verifyShiprocketCleanup} emptyMessage="No orders match this reconciliation view." /></section>}
        </div>}

        <div className={activePage === 'Orders' ? '' : 'hidden'}>
        <div className="mb-5 flex flex-wrap items-end justify-between gap-4">
          <div>
            <p className="text-sm font-medium text-[#ff6b35]">Orders</p>
            <h2 className="mt-1 text-2xl font-bold tracking-tight">{search ? 'Search results' : 'Operations queue'} <span className="font-medium text-slate-400">({visibleCount})</span></h2>
            <div className="relative mt-3 w-full max-w-md">
              <span className="absolute left-3 top-3 text-slate-400"><Icon name="search" size={17} /></span>
              <input ref={searchRef} value={searchDraft} onChange={e => setSearchDraft(e.target.value)} onKeyDown={e => { if (e.key === 'Enter') { setSearch(searchDraft.trim()); setPage(1) } }} className="w-full rounded-lg border border-slate-200 py-2.5 pl-9 pr-9 text-sm outline-none placeholder:text-slate-400 focus:border-orange-300 focus:ring-2 focus:ring-orange-100" placeholder="Search order number, customer or phone..." />
              {searchDraft && <button aria-label="Clear search" onClick={() => { setSearchDraft(''); setSearch(''); setPage(1); searchRef.current?.focus() }} className="absolute right-3 top-2.5 text-lg text-slate-400 hover:text-slate-700">×</button>}
            </div>
          </div>
          <div className="flex flex-wrap gap-2">
            <button onClick={() => void exportOrders('current', orders.map(order => order.internalId)).catch(error => setNotice(error.message))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-600">Export Current View</button>
            <button onClick={() => void exportOrders('full', []).catch(error => setNotice(error.message))} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-semibold text-slate-600">Export Full Workbook</button>
            <button onClick={() => void loadOrders()} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 shadow-sm hover:bg-slate-50">Refresh</button>
          </div>
        </div>

        <section className="mb-5 flex flex-wrap items-end gap-5">
          {[{ label: 'ORDERS', items: tabItems }, { label: 'DISPATCH', items: dispatchItems }].map(group => <div key={group.label}>
            <p className="mb-2 text-[10px] font-bold tracking-[.14em] text-slate-400">{group.label}</p>
            <div className="flex flex-wrap gap-2">{group.items.map(tab => (
              <button key={tab.key} onClick={() => { if (tab.key === 'shiprocket_cleanup') { setReconciliationFilter('cleanup_pending'); return } setReconciliationFilter(clearReconciliationFilter()); setQueue(tab.key); setPage(1); if (tab.key === 'labels_to_print') { refreshLabels(); void getActiveLabelBatches().then(batches => { if (batches[0]) { setActiveBatch(batches[0]); setPrintedLabels(new Set(batches[0].order_ids)) } }); setShowLabels(true) } }} className={`rounded-full px-4 py-2 text-sm font-medium ${(queue === tab.key && !reconciliationFilter) || (tab.key === 'shiprocket_cleanup' && reconciliationFilter === 'cleanup_pending') ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'}`}>
                {tab.label}
                <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] font-bold ${queue === tab.key ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-500'}`}>{summaryCounts[tab.key]}</span>
              </button>
            ))}</div>
          </div>)}
        </section>
        {queue === 'previous' && <div className="mb-3 flex gap-2" aria-label="Previous pending views">
          <button onClick={() => { setPendingView('follow_up'); setPage(1) }} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${pendingView === 'follow_up' ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200'}`}>Follow-up ({counts.follow_up})</button>
          <button onClick={() => { setPendingView('on_hold'); setAttemptFilter(null); setPage(1) }} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${pendingView === 'on_hold' ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200'}`}>On Hold ({counts.on_hold})</button>
        </div>}
        {queue === 'previous' && pendingView === 'follow_up' && <div className="mb-5 flex flex-wrap gap-2" aria-label="Attempt filters">
          {([['1', 'Attempt 1'], ['2', 'Attempt 2'], ['3', 'Attempt 3'], ['4_plus', 'Attempt 4+']] as const).map(([value, label]) => <button key={value} onClick={() => { setAttemptFilter(current => current === value ? null : value); setPage(1) }} className={`rounded-full px-3 py-1.5 text-xs font-semibold ${attemptFilter === value ? 'bg-orange-600 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200'}`}>{label}</button>)}
        </div>}

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-4 border-b border-slate-200 p-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="flex flex-wrap items-center gap-2">
              <Filter value={payment} onChange={value => { setPayment(value); setPage(1) }} options={['All', 'COD', 'Partial COD', 'Prepaid']} label="Payment Type" />
              <Filter value={risk} onChange={value => { setRisk(value); setPage(1) }} options={['All', 'High', 'Medium', 'Low']} label="Risk" />
              <Filter value={sort} onChange={value => { setSort(value); setPage(1) }} options={['Newest first', 'Oldest first', 'COD first', 'Prepaid first', 'Value high to low', 'Value low to high']} label="Sort" />
            </div>
          </div>

          {loading && orders.length === 0 ? (
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
              {loading && <div className="border-b border-slate-100 bg-slate-50 px-4 py-2 text-xs font-medium text-slate-500">Updating orders…</div>}
              {queue === 'printed_today' && orders.length > 0 && <div className="divide-y divide-slate-100 border-b border-slate-200 bg-slate-50/60">{orders.map(order => <div key={order.internalId} className="flex flex-wrap items-center gap-x-5 gap-y-2 px-4 py-3 text-xs"><span className="font-semibold text-slate-700">#{order.orderNumber}</span><span className="text-slate-500">Confirmed {order.shipment?.label_last_printed_at ? formatDateTime(order.shipment.label_last_printed_at) : '—'}</span><span className="text-slate-500">Operator: {order.shipment?.label_last_printed_by || '—'}</span><button onClick={() => void requestLabelReprint(order.internalId).then(() => { setNotice('Label returned to print queue.'); refreshLabels(); void loadOrders() }).catch(error => setNotice(error.message))} className="ml-auto font-semibold text-orange-600">Reprint</button></div>)}</div>}
              <OrdersTable orders={displayedOrders} repeatIds={repeatIds} onOpen={openOrder} loading={loading} emptyMessage={queue === 'printed_today' ? 'No labels have been confirmed today.' : 'No orders match your filters.'} />
              {queue !== 'shiprocket_cleanup' && <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 px-4 py-3">
                <p className="text-xs text-slate-500">Showing <span className="font-semibold text-slate-700">{total === 0 ? 0 : (page - 1) * pageSize + 1}–{Math.min(page * pageSize, total)}</span> of {total} orders</p>
                <div className="flex items-center gap-3 text-xs text-slate-500">
                  <label>Rows per page <select aria-label="Rows per page" value={pageSize} onChange={event => { setPageSize(Number(event.target.value) as 20 | 50 | 100); setPage(1) }} className="ml-1 rounded-md border border-slate-200 bg-white px-2 py-1.5"><option value={20}>20</option><option value={50}>50</option><option value={100}>100</option></select></label>
                  <button disabled={page <= 1 || loading} onClick={() => setPage(value => Math.max(1, value - 1))} className="rounded-md border border-slate-200 px-2.5 py-1.5 font-semibold disabled:opacity-40">Previous</button>
                  <span>Page {page} of {totalPages}</span>
                  <button disabled={page >= totalPages || loading} onClick={() => setPage(value => Math.min(totalPages, value + 1))} className="rounded-md border border-slate-200 px-2.5 py-1.5 font-semibold disabled:opacity-40">Next</button>
                </div>
              </div>}
            </>
          )}
        </section>
        </div>
      </main>

      {selectedOrder && (
        <OrderDrawer
          key={selectedOrder.internalId}
          order={selectedOrder}
          repeat={isRepeat}
          status={status}
          callLog={callLog}
          addressConfirmationComments={operations?.address_confirmation_comments || []}
          timelineEvents={[
            { action: 'Order Created', timestamp: selectedOrder.createdAt, operator: null },
            ...callLog.map(event => ({ action: `COD call: ${event.result}`, timestamp: event.timestamp, operator: event.operator })),
            ...(operations?.address_confirmation_comments || []).map(event => ({ action: 'Address confirmation comment', timestamp: event.timestamp, operator: event.operator })),
            ...(operations?.human_actions || []).filter(event => !['call_logged', 'address_confirmation_commented'].includes(event.action)).map(event => ({ action: event.action.replaceAll('_', ' '), timestamp: event.timestamp, operator: event.operator })),
            ...(operations?.timeline_events || []).map(event => ({ action: event.action.replaceAll('_', ' '), timestamp: event.timestamp, operator: event.operator })),
            ...(selectedOrder.shipment?.booked_at ? [{ action: `${selectedOrder.shipment.provider || 'Courier'} booking confirmed`, timestamp: selectedOrder.shipment.booked_at, operator: null }] : []),
            ...(selectedOrder.shipment?.shopify_fulfillment_synced_at ? [{ action: 'Shopify fulfilment synced', timestamp: selectedOrder.shipment.shopify_fulfillment_synced_at, operator: null }] : []),
            ...(selectedOrder.shipment?.label_last_printed_at ? [{ action: 'Label printing confirmed', timestamp: selectedOrder.shipment.label_last_printed_at, operator: selectedOrder.shipment.label_last_printed_by }] : []),
          ].sort((a, b) => new Date(a.timestamp).getTime() - new Date(b.timestamp).getTime())}
          callResult={callResult}
          callComment={callComment}
          setCallResult={setCallResult}
          setCallComment={setCallComment}
          addressDraft={addressDraft}
          setAddressDraft={setAddressDraft}
          courierSyncMessage={courierSyncMessage}
          addressVerificationLine={addressVerifiedLabel}
          onClose={() => { setSelectedOrderId(null); setSelectedOrderSnapshot(null) }}
          onSaveCallLog={() => void saveCallLog()}
          onSaveAddress={saveAndVerifyAddress}
          onSaveAddressConfirmation={() => void saveAddressConfirmation()}
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
          onSaveManualShadowfax={saveManualShadowfax}
          showShadowfaxDirectTest={selectedOrder.orderNumber === '324541' && ['owner', 'admin'].includes(authUser?.role || '')}
          onTestShadowfaxDirect={() => void testShadowfaxDirect()}
          shadowfaxTestState={shadowfaxTestState}
          onResetShadowfaxDirect={() => void resetShadowfaxDirect()}
          onRefreshShipment={() => void refreshShipment()}
          onReconcileShipment={() => void reconcileShipment()}
          onCancelShipment={() => void cancelShipment()}
          onRetryShiprocketCleanup={() => { if (selectedOrder) void retryShiprocketCleanup(selectedOrder.internalId).then(result => { if (result.status === 'cancelled' || result.status === 'not_applicable') setCourierError(''); else setCourierError(result.error || `Shiprocket cleanup: ${result.status}`); setOperations(current => current) }).catch(error => setCourierError(error.message)) }}
          onSyncShopifyFulfillment={() => void syncFulfillment()}
          onDownloadLabel={() => retrieveLabel('download')}
          onPrintLabel={() => retrieveLabel('print')}
        />
      )}

      {selectedOrder && cancellationPreflight && <div className="fixed inset-0 z-[80] grid place-items-center bg-slate-950/55 p-4"><div className="w-full max-w-lg rounded-xl bg-white p-5 shadow-2xl"><h2 className="text-lg font-bold text-rose-700">Confirm order cancellation</h2><p className="mt-2 text-sm text-slate-600">Each applicable system is attempted and reported separately.</p><div className="mt-4 space-y-2 rounded-lg bg-slate-50 p-3 text-sm"><p>Mumchies OS: Will cancel</p><p>Shopify: {cancellationPreflight.shopify.exists ? 'Will cancel' : 'Not applicable'}</p><p>Shiprocket: {cancellationPreflight.shiprocket.exists ? `Will cancel unbooked order ${cancellationPreflight.shiprocket.order_id || ''}` : cancellationPreflight.shiprocket.lookup_error ? `Lookup failed: ${cancellationPreflight.shiprocket.lookup_error}` : 'Not applicable'}</p><p>Shipment/AWB: {cancellationPreflight.shipment.awb || cancellationPreflight.shiprocket.awb || 'None detected'}</p></div>{!cancellationPreflight.allowed && <p className="mt-3 rounded-lg bg-rose-50 p-3 text-sm font-semibold text-rose-700">Blocked: {cancellationPreflight.blocked_reason}</p>}{cancellationResult && <div className="mt-3 rounded-lg border border-slate-200 p-3 text-sm">{Object.entries(cancellationResult).map(([system, result]) => <p key={system}><span className="font-semibold capitalize">{system.replace('_', ' ')}:</span> {result.status}{result.error ? ` — ${result.error}` : ''}</p>)}</div>}<div className="mt-5 flex justify-end gap-2"><button onClick={() => { setCancellationPreflight(null); setCancellationResult(null) }} className="rounded-lg px-4 py-2 text-sm font-semibold text-slate-600">Close</button><button disabled={!cancellationPreflight.allowed || cancellationLoading || Boolean(cancellationResult)} onClick={() => { setCancellationLoading(true); void cancelOrder(selectedOrder.internalId, callComment).then(result => { setCancellationResult(result.results); setOperations(result.operations); setOrders(previous => previous.map(order => order.internalId === selectedOrder.internalId ? { ...order, operationalStatus: 'Cancelled' } : order)) }).catch(error => setNotice(error.message)).finally(() => setCancellationLoading(false)) }} className="rounded-lg bg-rose-600 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">{cancellationLoading ? 'Cancelling…' : 'Cancel affected systems'}</button></div></div></div>}

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

function Filter({ value, onChange, options, label }: { value: string; onChange: (value: string) => void; options: string[]; label?: string }) {
  return <label className="flex items-center gap-1 text-xs text-slate-500">{label && <span>{label}</span>}<select aria-label={label} value={value} onChange={e => onChange(e.target.value)} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium text-slate-600 outline-none focus:border-orange-300">{options.map(option => <option key={option}>{option}</option>)}</select></label>
}

const reconciliationReason = (reason: string | null) => ({
  'routed directly to another courier': 'Direct courier',
  'not yet synced to Shiprocket': 'Awaiting Shiprocket sync',
  'mapping issue': 'Mapping issue',
  'Shiprocket order already cancelled': 'Shiprocket cancelled',
  other: 'Other',
}[reason || 'other'] || reason || 'Other')

export function OrdersTable({ orders: tableOrders, repeatIds: repeats, onOpen, loading: tableLoading = false, emptyMessage, reconciliationRows: metadata = [], reconciliationFilter: filter = null, cleanupRecords: cleanup = [], cleanupResults: results = {}, onCleanup, onVerify }: {
  orders: Order[]
  repeatIds: Set<string>
  onOpen: (orderId: string) => void
  loading?: boolean
  emptyMessage: string
  reconciliationRows?: ReconciliationRecord[]
  reconciliationFilter?: ReconciliationFilter | null
  cleanupRecords?: ShiprocketCleanupRecord[]
  cleanupResults?: Record<string, ShiprocketCancellationResult>
  onCleanup?: (record: ShiprocketCleanupRecord) => void
  onVerify?: (record: ShiprocketCleanupRecord) => void
}) {
  const showReason = filter === 'missing_in_shiprocket' || filter === 'cleanup_pending'
  const showShiprocket = filter === 'shiprocket_new' || filter === 'both' || filter === 'cleanup_pending'
  const columns = ['Order No', 'Date / Time', 'Customer', 'Amount', 'Payment', 'Risk', 'Status', 'Engage', ...(showReason ? ['Reconciliation Reason'] : []), ...(showShiprocket ? ['Shiprocket Status'] : []), 'Actions']
  return <div className={`overflow-x-auto transition-opacity ${tableLoading ? 'opacity-60' : ''}`}><table className="w-full min-w-[980px] text-left"><thead className="bg-slate-50 text-[11px] font-bold uppercase tracking-wider text-slate-400"><tr>{columns.map(column => <th key={column} className="whitespace-nowrap px-4 py-3.5">{column}</th>)}</tr></thead><tbody className="divide-y divide-slate-100">{tableOrders.map((order, index) => { const record = metadata[index]; const cleanupRecord = record?.shiprocket_order_id ? cleanup.find(value => value.shiprocket_order_id === record.shiprocket_order_id) : undefined; const cleanupResult = cleanupRecord ? results[cleanupRecord.shiprocket_order_id] || cleanupRecord.last_verification : null; return <OrderRow key={`${order.internalId}:${record?.shiprocket_order_id || ''}`} order={order} repeat={repeats.has(order.internalId)} onClick={() => onOpen(order.internalId)} drawerEnabled={record?.order !== null} reconciliationReason={showReason ? reconciliationReason(record?.reason || null) : null} shiprocketStatus={showShiprocket ? record?.shiprocket_status || '—' : null} extraActions={<>{filter === 'cleanup_pending' && cleanupRecord && onCleanup && <button onClick={event => { event.stopPropagation(); onCleanup(cleanupRecord) }} className="rounded-md border border-rose-200 px-2 py-1 text-[10px] font-semibold text-rose-700">Safe Cancel</button>}{cleanupResult && ['inconsistent', 'unverified'].includes(cleanupResult.status) && cleanupRecord && onVerify && <button onClick={event => { event.stopPropagation(); onVerify(cleanupRecord) }} className="rounded-md border border-amber-200 px-2 py-1 text-[10px] font-semibold text-amber-700">Retry verification</button>}{record?.shiprocket_order_id && <a onClick={event => event.stopPropagation()} href={`https://app.shiprocket.in/orders/processing?search=${encodeURIComponent(record.order_number)}`} target="_blank" rel="noreferrer" className="rounded-md border border-slate-200 px-2 py-1 text-[10px] font-semibold text-slate-600">Shiprocket</a>}</>} /> })}</tbody></table>{tableOrders.length === 0 && <div className="py-14 text-center text-sm text-slate-400">{emptyMessage}</div>}</div>
}

const OrderRow = memo(function OrderRow({ order, repeat, onClick, drawerEnabled = true, reconciliationReason: reason = null, shiprocketStatus = null, extraActions = null }: { order: Order; repeat: boolean; onClick: () => void; drawerEnabled?: boolean; reconciliationReason?: string | null; shiprocketStatus?: string | null; extraActions?: ReactNode }) {
  const placed = formatOrderDateTime(order.createdAt)
  const attempt = order.callAttemptCount > 0 ? `Attempt ${order.callAttemptCount > 5 ? '5+' : order.callAttemptCount}` : null
  return (
    <tr onClick={() => { if (drawerEnabled) onClick() }} style={{ contentVisibility: 'auto', containIntrinsicSize: '0 56px' }} className={`${drawerEnabled ? 'cursor-pointer' : ''} text-sm text-slate-600 hover:bg-orange-50/50`}>
      <td className="px-4 py-3.5 font-semibold text-slate-800"><span className="inline-flex items-center gap-1">{displayedOrderNumber(order.orderNumber)}<CopyButton value={orderNumberClipboardValue(order.orderNumber)} label="order number" stopPropagation /></span></td>
      <td className="whitespace-nowrap px-4 py-3.5"><p className="font-medium text-slate-700">{placed.date}</p><p className="text-xs text-slate-400">{placed.time}</p></td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          {(order.customerId || order.customerOrdersCount != null) && <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${repeat ? 'bg-violet-50 text-violet-700' : 'bg-slate-100 text-slate-600'}`}>{repeat ? '[RPT]' : '[NEW]'}</span>}
          <span className="font-medium text-slate-700">{order.customerName}</span>
        </div>
      </td>
      <td className="px-4 py-3.5 font-semibold text-slate-800">{formatMoney(order.amount)}</td>
      <td className="px-4 py-3.5"><span className={`rounded-md px-2 py-1 text-[11px] font-bold ${order.payment === 'Prepaid' ? 'bg-emerald-50 text-emerald-700' : order.payment === 'Partial COD' ? 'bg-orange-100 text-orange-800' : 'bg-amber-50 text-amber-700'}`}>{order.payment}</span>{order.payment !== 'Prepaid' && attempt && <p className="mt-1 text-[10px] font-semibold text-slate-400">{attempt}</p>}{order.payment === 'Partial COD' && <p className="mt-1 whitespace-nowrap text-[10px] text-slate-500">{formatMoney(order.paidAmount)} paid · {formatMoney(order.codCollectableAmount)} due</p>}</td>
      <td className="px-4 py-3.5"><span className={`rounded-md px-2 py-1 text-[11px] font-bold ring-1 ring-inset ${riskStyle[order.risk]}`}>{order.risk} Risk</span></td>
      <td className="px-4 py-3.5"><OrderStatusBadge order={order} /></td>
      <td className="px-2 py-3.5"><div className="flex gap-1"><EngageCircle label="OC" stageName="Order Confirmation" value={order.orderConfirmation} message={order.orderConfirmationMessage} /><EngageCircle label="AV" stageName="Address Verification" value={order.addressConfirmation} message={order.addressConfirmationMessage} enabled={engageCategory(order.orderConfirmation) === 'successful'} /><EngageCircle label="CP" stageName="COD to Prepaid" value={order.codToPrepaid} message={order.codToPrepaidMessage} enabled={engageCategory(order.orderConfirmation) === 'successful' && engageCategory(order.addressConfirmation) === 'successful'} /></div></td>
      {reason && <td className="px-4 py-3.5 text-xs font-medium text-amber-700">{reason}</td>}
      {shiprocketStatus && <td className="px-4 py-3.5 text-xs font-semibold text-slate-600">{shiprocketStatus}</td>}
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-1">
          {drawerEnabled && <button onClick={e => { e.stopPropagation(); onClick() }} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Icon name="eye" size={16} /></button>}
          {extraActions}
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
  addressConfirmationComments,
  timelineEvents,
  callResult,
  callComment,
  setCallResult,
  setCallComment,
  addressDraft,
  setAddressDraft,
  courierSyncMessage,
  addressVerificationLine,
  onClose,
  onSaveCallLog,
  onSaveAddressConfirmation,
  onSaveAddress,
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
  onSaveManualShadowfax,
  showShadowfaxDirectTest,
  onTestShadowfaxDirect,
  shadowfaxTestState,
  onResetShadowfaxDirect,
  onRefreshShipment,
  onReconcileShipment,
  onCancelShipment,
  onRetryShiprocketCleanup,
  onSyncShopifyFulfillment,
  onDownloadLabel,
  onPrintLabel,
}: {
  order: Order
  repeat: boolean
  status: string
  callLog: OrderOperations['call_logs']
  addressConfirmationComments: OrderOperations['address_confirmation_comments']
  timelineEvents: { action: string; timestamp: string; operator: string | null }[]
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
  courierSyncMessage: string
  addressVerificationLine: string
  onClose: () => void
  onSaveCallLog: () => void
  onSaveAddress: () => Promise<{ operations: OrderOperations; validation: { status: string; blockers: string[]; warnings: string[]; shiprocket_message: string }; verified: boolean } | undefined>
  onSaveAddressConfirmation: () => void
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
  onSaveManualShadowfax: (payload: { awb?: string; provider_id?: string; service_name?: string; booked_at?: string; freight?: number; note?: string }) => Promise<void>
  showShadowfaxDirectTest: boolean
  onTestShadowfaxDirect: () => void
  shadowfaxTestState: ShadowfaxDirectTestState | null
  onResetShadowfaxDirect: () => void
  onRefreshShipment: () => void
  onReconcileShipment: () => void
  onCancelShipment: () => void
  onRetryShiprocketCleanup: () => void
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
  const [workflowError, setWorkflowError] = useState('')
  const [showShadowfaxForm, setShowShadowfaxForm] = useState(false)
  const [manualShadowfax, setManualShadowfax] = useState({ awb: '', provider_id: '', service_name: '', booked_at: new Date().toISOString().slice(0, 16), freight: '', note: '' })
  const autoLookupKeyRef = useRef('')

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
    'customer phone': 'Add a valid customer phone',
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
  const bookingBlocker = bookingEligibility?.shipment_exists
    ? 'Shipment already booked'
    : visibleMissing[0]
      || (!selectedCourierId ? 'Select a courier service'
        : !selectedCourier ? 'Selected courier response is incomplete'
          : !selectedCourier.booking_supported ? (selectedCourier.provider === 'delhivery' ? 'Direct booking is unavailable for this rate' : 'Selected courier does not support booking')
            : null)
  const autoLookupKey = `${order.internalId}:${packageNumbers.weight_kg}:${packageNumbers.length_cm}:${packageNumbers.breadth_cm}:${packageNumbers.height_cm}:${bookingEligibility?.eligible}:${addressDraft.pincode}:${addressDraft.phone}`
  useEffect(() => {
    if (!canCheckCouriers || courierLoading || courierError || autoLookupKeyRef.current === autoLookupKey) return
    autoLookupKeyRef.current = autoLookupKey
    onCheckCouriers(packageNumbers)
  }, [autoLookupKey, canCheckCouriers, courierError, courierLoading, onCheckCouriers, packageNumbers])
  return (
    <div className="fixed inset-0 z-40">
      <button aria-label="Close order drawer" onClick={onClose} className="absolute inset-0 bg-slate-950/35 backdrop-blur-[1px]" />
      <aside className="absolute inset-y-0 right-0 flex h-full w-[92vw] max-w-[760px] flex-col bg-white shadow-2xl md:w-[46vw]">
        <header className="border-b border-slate-200 px-5 py-4">
          <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-medium text-slate-400">Order details</p>
            <h2 className="mt-0.5 flex items-center gap-1 text-lg font-bold">Order {displayedOrderNumber(order.orderNumber)}<CopyButton value={orderNumberClipboardValue(order.orderNumber)} label="order number" /></h2>
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
          <Section title="Engage RTO Suite">
            <EngageProgress stages={[
              { abbreviation: 'OC', name: 'Order Confirmation', value: order.orderConfirmation, message: order.orderConfirmationMessage },
              { abbreviation: 'AV', name: 'Address Verification', value: order.addressConfirmation, message: order.addressConfirmationMessage },
              { abbreviation: 'CP', name: 'COD → Prepaid', value: order.codToPrepaid, message: order.codToPrepaidMessage },
            ]} lastSynced={order.engageLastSyncedAt ? formatDateTime(order.engageLastSyncedAt) : 'Not synced'} />
          </Section>
          <Section title="Customer">
            <div className="grid grid-cols-2 gap-3 text-sm">
              <KeyValue label="Customer Name" value={order.customerName} />
              <div><KeyValue label="Mobile" value={order.phone || 'No phone'} />{order.phone && <CopyButton value={order.phone} label="phone number" />}</div>
              <KeyValue label="Email" value={order.email || 'No email'} />
              {(order.customerId || order.customerOrdersCount != null) ? <KeyValue label="Customer Type" value={repeat ? '[RPT]' : '[NEW]'} /> : <KeyValue label="Customer Type" value="—" />}
            </div>
          </Section>

          <Section title="Shipping Address">
            <div className="mb-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-600">
              <p className={`font-medium ${hasVerifiedAddress ? 'text-emerald-700' : 'text-amber-700'}`}>{verificationLine}</p>
            </div>
            <div className="grid gap-3 sm:grid-cols-2">
              <Field label="Customer Name" value={addressDraft.customer_name} onChange={value => setAddressDraft({ ...addressDraft, customer_name: value })} />
              <Field label="Phone" value={addressDraft.phone} onChange={value => setAddressDraft({ ...addressDraft, phone: value })} />
              <MultilineField label="Address Line 1" value={addressDraft.address_line1} onChange={value => setAddressDraft({ ...addressDraft, address_line1: value })} />
              <MultilineField label="Address Line 2" value={addressDraft.address_line2} onChange={value => setAddressDraft({ ...addressDraft, address_line2: value })} />
              <MultilineField label="Landmark" value={addressDraft.landmark} onChange={value => setAddressDraft({ ...addressDraft, landmark: value })} />
              <div className="grid gap-3 sm:col-span-2 sm:grid-cols-3">
                <Field label="City" value={addressDraft.city} onChange={value => setAddressDraft({ ...addressDraft, city: value })} />
                <Field label="State" value={addressDraft.state} onChange={value => setAddressDraft({ ...addressDraft, state: value })} />
                <Field label="PIN Code" value={addressDraft.pincode} onChange={value => setAddressDraft({ ...addressDraft, pincode: value })} />
              </div>
            </div>
            <div className="mt-4 flex flex-wrap gap-2">
              <button onClick={() => { setAddressReviewLoading(true); void onSaveAddress().then(result => { if (result) setAddressReview(result.validation) }).finally(() => setAddressReviewLoading(false)) }} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white">{addressReviewLoading ? 'Saving & Verifying…' : 'Save & Verify Address'}</button>
              <button onClick={() => { const query = [addressDraft.address_line1, addressDraft.address_line2, addressDraft.landmark, addressDraft.city, addressDraft.state, addressDraft.pincode, 'India'].filter(Boolean).join(', '); window.open(`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(query)}`, '_blank', 'noopener,noreferrer') }} className="rounded-lg border border-slate-200 px-3 py-2 text-sm font-semibold text-slate-600">Open in Google Maps</button>
            </div>
            {addressReview && <div className={`mt-3 rounded-lg px-3 py-2 text-sm ${addressReview.blockers.length ? 'bg-rose-50 text-rose-700' : addressReview.warnings.length ? 'bg-amber-50 text-amber-800' : 'bg-emerald-50 text-emerald-700'}`}><p className="font-semibold">{addressReview.status}</p>{addressReview.blockers.map(value => <p key={value}>• {value}</p>)}{addressReview.warnings.map(value => <p key={value}>• {value}</p>)}<p className="mt-1 text-xs opacity-80">{addressReview.shiprocket_message}</p><p className="mt-1 text-[11px] opacity-70">Advisory only; Maps results and warnings do not block verification.</p></div>}
            <div className="mt-3 space-y-2 text-xs text-slate-600">
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

          {order.externalTracking?.awb && !shipment && (
            <Section title="Tracking">
              <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                <p className="font-semibold">Shipped via {order.externalTracking.provider || 'courier'}</p>
                <p>AWB {order.externalTracking.awb}</p>
                {order.externalTracking.status && <p>Status: {order.externalTracking.status}</p>}
                {order.externalTracking.trackingUrl && (
                  <a href={order.externalTracking.trackingUrl} target="_blank" rel="noopener noreferrer" className="mt-2 inline-block rounded-md border border-emerald-200 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-800">
                    Track Shipment
                  </a>
                )}
              </div>
            </Section>
          )}

          <Section title={orderContactSectionTitle(isPrepaid)}>
            <div className="space-y-3">
              {isPrepaid ? <div className="grid gap-2 lg:grid-cols-[2fr_auto]"><input value={callComment} onChange={e => setCallComment(e.target.value)} placeholder="Address confirmation comment (optional)" className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none" /><button onClick={onSaveAddressConfirmation} className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white">Save Comment</button></div> : <div className="grid gap-2 lg:grid-cols-[1fr_2fr_auto]">
                <select value={callResult} onChange={e => setCallResult(e.target.value as CallResult)} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm outline-none">
                  {callResults.map(result => <option key={result} value={result}>{callResultLabel(result)}</option>)}
                </select>
                <input value={callComment} onChange={e => setCallComment(e.target.value)} placeholder="Comment" className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none" />
                <button onClick={onSaveCallLog} className="rounded-lg bg-slate-900 px-4 py-2.5 text-sm font-semibold text-white">Save</button>
              </div>}
              {!isPrepaid && <div className="space-y-2">
                {shouldShowCodWhatsApp(order.paymentType, callLog[0]?.result) && <button onClick={() => {
                  const url = codWhatsAppUrl(addressDraft.phone || order.phone)
                  if (!url) { setWorkflowError('A valid Indian mobile number is required to open WhatsApp.'); return }
                  setWorkflowError('')
                  window.open(url, '_blank', 'noopener,noreferrer')
                  void recordCodWhatsAppOpened(order.internalId).catch(error => setWorkflowError(error.message))
                }} className="rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-800">Send WhatsApp</button>}
                {workflowError && <p className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{workflowError}</p>}
                {callLog.length === 0 ? <p className="text-sm text-slate-400">No call attempts logged yet.</p> : callLog.map(entry => (
                  <div key={`${entry.timestamp}-${entry.result}`} className="rounded-lg border border-slate-100 px-3 py-2 text-sm">
                    <div className="flex items-center justify-between">
                      <span className="font-semibold text-slate-700">{entry.result}</span>
                      <span className="text-xs text-slate-400">{formatDateTime(entry.timestamp)}</span>
                    </div>
                    <p className="mt-1 text-xs text-slate-500">Operator: {entry.operator}</p>
                    {entry.comment && <p className="mt-1 text-xs text-slate-600">{entry.comment}</p>}
                  </div>
                ))}
              </div>}
              {isPrepaid && <div className="space-y-2">{addressConfirmationComments.length === 0 ? <p className="text-sm text-slate-400">No address confirmation comments yet.</p> : addressConfirmationComments.map(entry => <div key={entry.timestamp} className="rounded-lg border border-slate-100 px-3 py-2 text-sm"><div className="flex justify-between gap-3"><span className="font-semibold text-slate-700">Address confirmation</span><span className="text-xs text-slate-400">{formatDateTime(entry.timestamp)}</span></div><p className="mt-1 text-xs text-slate-500">Operator: {entry.operator}</p>{entry.comment && <p className="mt-1 text-xs text-slate-600">{entry.comment}</p>}</div>)}</div>}
            </div>
          </Section>

          <Section title="Courier Booking">
            <div className="space-y-4 text-sm text-slate-600">
              {hasShipmentEvidence(order) && !shipment ? (
                <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-3 text-sm text-slate-600">
                  This order already has an existing shipment or fulfilment (see Tracking above). Booking controls are unavailable to prevent a duplicate shipment.
                </div>
              ) : (
              <>
              <div className="grid gap-3 sm:grid-cols-4">
                <Field testId="package-weight" label="Weight (kg)" value={packageDraft.weight_kg} onChange={value => setPackageDraft({ ...packageDraft, weight_kg: value })} />
                <Field testId="package-length" label="Length (cm)" value={packageDraft.length_cm} onChange={value => setPackageDraft({ ...packageDraft, length_cm: value })} />
                <Field testId="package-breadth" label="Breadth (cm)" value={packageDraft.breadth_cm} onChange={value => setPackageDraft({ ...packageDraft, breadth_cm: value })} />
                <Field testId="package-height" label="Height (cm)" value={packageDraft.height_cm} onChange={value => setPackageDraft({ ...packageDraft, height_cm: value })} />
              </div>
              <div className="rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                <p className="font-medium text-slate-700">Eligibility</p>
                {bookingEligibility === null
                  ? <p className="mt-1">Checking eligibility…</p>
                  : visibleMissing.length === 0
                    ? <p className="mt-1">Eligible for courier lookup</p>
                    : <ul className="mt-1 list-disc space-y-0.5 pl-5">{visibleMissing.map(requirement => <li key={requirement}>{requirement}</li>)}</ul>}
              </div>
              {courierError && <div className="rounded-lg bg-rose-50 px-3 py-2 text-sm text-rose-700">{courierError}{courierError.startsWith('Shiprocket cleanup') ? <button onClick={onRetryShiprocketCleanup} className="ml-3 rounded-md border border-rose-200 bg-white px-2 py-1 font-semibold">Retry cleanup</button> : <button onClick={() => { autoLookupKeyRef.current = ''; onCheckCouriers(packageNumbers) }} className="ml-3 rounded-md border border-rose-200 bg-white px-2 py-1 font-semibold">Retry courier lookup</button>}</div>}
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
              {selectedCourier?.provider === 'shadowfax' && <p className="rounded-lg bg-amber-50 px-3 py-2 font-semibold text-amber-800">Manual booking on Shadowfax required</p>}
              {showShadowfaxDirectTest && <div className="flex flex-wrap gap-2"><button type="button" disabled={bookingLoading || shadowfaxTestState?.final_test_state === 'legacy_attempt_observed_without_diagnostics' || Boolean(shadowfaxTestState?.create_request_started_at)} onClick={onTestShadowfaxDirect} className="rounded-lg border border-violet-300 bg-violet-50 px-3 py-2 text-sm font-semibold text-violet-800 disabled:opacity-50">Test Shadowfax Direct</button>{shadowfaxTestState?.final_test_state === 'legacy_attempt_observed_without_diagnostics' && <button type="button" disabled={bookingLoading} onClick={onResetShadowfaxDirect} className="rounded-lg border border-amber-300 bg-amber-50 px-3 py-2 text-sm font-semibold text-amber-800 disabled:opacity-50">Reset Shadowfax Test</button>}</div>}
              {showShadowfaxDirectTest && shadowfaxTestState && <details open className="rounded-lg border border-violet-200 bg-violet-50/40 p-3 text-xs text-slate-700">
                <summary className="cursor-pointer font-semibold text-violet-900">Shadowfax direct test status</summary>
                <dl className="mt-2 grid gap-x-3 gap-y-1 sm:grid-cols-2">{Object.entries(shadowfaxTestState).map(([key, value]) => <div key={key}><dt className="font-semibold">{key.replaceAll('_', ' ')}</dt><dd className="break-words">{value == null ? '—' : typeof value === 'object' ? JSON.stringify(value) : String(value)}</dd></div>)}</dl>
              </details>}
              {showShadowfaxForm && selectedCourier?.provider === 'shadowfax' && <div className="space-y-3 rounded-xl border border-slate-200 p-3">
                <p className="font-semibold text-slate-800">Confirm manual Shadowfax booking</p>
                <div className="grid gap-2 sm:grid-cols-2"><Field label="AWB" value={manualShadowfax.awb} onChange={awb => setManualShadowfax({ ...manualShadowfax, awb })} /><Field label="Shipment / Order ID" value={manualShadowfax.provider_id} onChange={provider_id => setManualShadowfax({ ...manualShadowfax, provider_id })} /><Field label="Service name" value={manualShadowfax.service_name} onChange={service_name => setManualShadowfax({ ...manualShadowfax, service_name })} /><Field label="Booking date/time" value={manualShadowfax.booked_at} onChange={booked_at => setManualShadowfax({ ...manualShadowfax, booked_at })} /><Field label="Freight (optional)" value={manualShadowfax.freight} onChange={freight => setManualShadowfax({ ...manualShadowfax, freight })} /><Field label="Operator note" value={manualShadowfax.note} onChange={note => setManualShadowfax({ ...manualShadowfax, note })} /></div>
                <button disabled={bookingLoading || (!manualShadowfax.awb.trim() && !manualShadowfax.provider_id.trim())} onClick={() => void onSaveManualShadowfax({ ...manualShadowfax, booked_at: new Date(manualShadowfax.booked_at).toISOString(), freight: manualShadowfax.freight ? Number(manualShadowfax.freight) : undefined }).then(() => setShowShadowfaxForm(false)).catch(() => undefined)} className="rounded-lg bg-slate-900 px-4 py-2 text-sm font-semibold text-white disabled:opacity-40">Save manual shipment</button>
                {!manualShadowfax.awb.trim() && !manualShadowfax.provider_id.trim() && <p className="text-xs text-amber-700">Enter an AWB or Shadowfax shipment/order ID.</p>}
              </div>}
              {shipment && (
                <div className="rounded-lg border border-emerald-100 bg-emerald-50 px-3 py-3 text-sm text-emerald-800">
                  <p className="font-semibold">Provider: {shipment.provider || 'Shiprocket'}</p>
                  <p>Booking status: {shipment.booking_status || '—'}</p>
                  <p>Courier: {shipment.courier_name || '—'}</p>
                  <p>AWB: {shipment.awb || '—'}</p>
                  <p>Shipment ID: {shipment.shipment_id || '—'}</p>
                  <p>Booked at: {shipment.booked_at ? formatDateTime(shipment.booked_at) : '—'}</p>
                  <p>Latest status: {shipment.latest_status || '—'}</p>
                  {shipment.booking_mode && <p>Booking mode: {shipment.booking_mode}</p>}
                  {shipment.courier_service && <p>Service: {shipment.courier_service}</p>}
                  {shipment.booking_freight != null && <p>Freight: {formatMoney(shipment.booking_freight)}</p>}
                  {shipment.booking_operator && <p>Operator: {shipment.booking_operator}</p>}
                  {shipment.booking_note && <p>Note: {shipment.booking_note}</p>}
                  {shipment.provider && shipment.shipment_id && (
                    <button onClick={onRefreshShipment} disabled={shipmentRefreshLoading} className="mt-2 rounded-md border border-emerald-200 bg-white px-3 py-1.5 text-xs font-semibold text-emerald-800 disabled:opacity-60">
                      {shipmentRefreshLoading ? 'Refreshing…' : 'Refresh Shipment Status'}
                    </button>
                  )}
                  {(shipment.booking_confidence === 'uncertain' || shipment.reconciliation_status === 'pending' || shipment.reconciliation_status === 'manual_review') && <button onClick={onReconcileShipment} disabled={shipmentRefreshLoading} className="ml-2 mt-2 rounded-md border border-amber-200 bg-white px-3 py-1.5 text-xs font-semibold text-amber-800 disabled:opacity-60">Retry Verification</button>}
                  {shipment.reconciliation_error && <p className="mt-2 text-xs text-rose-700">{shipment.reconciliation_error}</p>}
                </div>
              )}
              {courierOptions.length === 0 && !courierLoading && !courierError && <p className="text-xs text-slate-500">{courierSyncMessage || (canCheckCouriers ? 'No courier options are available.' : 'Complete the requirements above to load courier options automatically.')}</p>}
              </>
              )}
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
                {timelineEvents.map((event, index) => (
                  <li key={`${event.action}-${event.timestamp}-${index}`} className="relative pb-5 pl-5 last:pb-0">
                    <span className="absolute -left-[5px] top-1 h-2.5 w-2.5 rounded-full bg-[#ff6b35]" />
                    <p className="text-sm font-medium capitalize text-slate-700">{event.action}</p>
                    <p className="mt-0.5 text-xs text-slate-400">{formatDateTime(event.timestamp)}{event.operator ? ` · ${event.operator}` : ''}</p>
                  </li>
                ))}
              </ol>
            </details>
          </Section>
        </div>

        <footer className="absolute inset-x-0 bottom-0 flex items-center gap-2 border-t border-slate-200 bg-white px-4 py-3 shadow-[0_-8px_20px_rgba(15,23,42,.05)]">
          {shipment?.awb ? (
            <>
              {shipment.provider ? (
                <button disabled={labelLoading} onClick={onDownloadLabel} className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2.5 text-sm font-semibold text-white disabled:opacity-60">
                  <Icon name="truck" size={16} />
                  {labelLoading ? 'Preparing 4×6 label…' : 'Download 4×6 Label'}
                </button>
              ) : <div className="flex flex-1 items-center justify-center rounded-lg bg-slate-100 px-3 py-2.5 text-sm font-semibold text-slate-500">Provider label unavailable</div>}
              <button disabled={labelLoading} onClick={onPrintLabel} className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700 disabled:opacity-60">Open / Print Label</button>
              <button onClick={() => window.open(shipment.tracking_url || `${apiBase}/api/v1/couriers/shiprocket/orders/${order.internalId}/tracking`, '_blank', 'noopener,noreferrer')} className="rounded-lg border border-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-700">Open Tracking</button>
              <button disabled={shipmentRefreshLoading || ['picked_up', 'in_transit', 'out_for_delivery', 'delivered', 'rto'].includes(shipment.normalized_status || '')} onClick={onCancelShipment} className="rounded-lg border border-rose-200 px-3 py-2.5 text-sm font-semibold text-rose-700 disabled:opacity-40">Cancel Shipment</button>
            </>
          ) : (
            <div className="flex flex-1 flex-col gap-1"><button
              disabled={!canBookShipment}
              onClick={() => selectedCourier?.provider === 'shadowfax' ? setShowShadowfaxForm(true) : void onBookShipment(packageNumbers)}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-slate-900 px-3 py-2.5 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:bg-slate-200 disabled:text-slate-500"
            >
              <Icon name="truck" size={16} />
              {bookingLoading ? `Saving ${selectedCourier?.courier_name || 'courier'}…` : selectedCourier?.provider === 'shadowfax' ? 'Mark as shipped through Shadowfax' : selectedCourierId ? 'Book Shipment' : 'Select a courier above'}
            </button>{!canBookShipment && bookingBlocker && <p className="text-center text-[11px] font-medium text-amber-700">{bookingBlocker}</p>}</div>
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

export function MultilineField({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return <label className="block sm:col-span-2"><span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</span><textarea rows={2} value={value} onChange={event => onChange(event.target.value)} className="w-full resize-y overflow-x-hidden whitespace-pre-wrap break-words rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-orange-300 focus:ring-2 focus:ring-orange-100" /></label>
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
