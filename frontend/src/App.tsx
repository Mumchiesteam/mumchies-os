import type { ReactNode } from 'react'
import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  addOrderCallLog,
  formatMoney,
  getOrderOperations,
  getOrders,
  saveOrderAddress,
  verifyOrderAddress,
  type Order,
  type OrderOperations,
  type RiskLevel,
} from './services/orders'

type IconName = 'grid' | 'bag' | 'alert' | 'users' | 'chart' | 'settings' | 'search' | 'bell' | 'filter' | 'chevron' | 'more' | 'eye' | 'truck' | 'calendar' | 'close' | 'copy' | 'phone' | 'external' | 'repeat' | 'tag' | 'edit' | 'call'
type TabKey = 'today' | 'previous' | 'ndr' | 'all'
type CallResult = 'No Answer' | 'Busy' | 'Switched Off' | 'Callback Requested' | 'Confirmed' | 'Cancelled' | 'Wrong Number'
type OperationalStatus = 'Call Pending' | 'Callback Required' | 'Address Verification Pending' | 'Ready for Booking' | 'Booked' | 'Shipped' | 'NDR' | 'Delivered' | 'Cancelled' | 'Needs Review'

const navItems = ['Dashboard', 'Orders', 'NDR', 'Customers', 'Reports', 'Settings'] as const
const tabItems: { key: TabKey; label: string }[] = [
  { key: 'today', label: "Today's Orders" },
  { key: 'previous', label: 'Previous Pending Orders' },
  { key: 'ndr', label: 'NDR' },
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
const formatDateTime = (value: string) => new Intl.DateTimeFormat('en-IN', { day: '2-digit', month: 'short', year: 'numeric', hour: '2-digit', minute: '2-digit' }).format(new Date(value))
const isCancelled = (order: Order) => Boolean(order.cancelledAt || order.shopifyStatus === 'cancelled' || (order.payment === 'COD' && order.tags.join(' ').toLowerCase().includes('cancel')))
const isShipped = (order: Order) => {
  const status = `${order.fulfillmentStatus || ''} ${order.shopifyStatus || ''} ${order.tags.join(' ')}`.toLowerCase()
  return status.includes('fulfilled') || status.includes('partial') || status.includes('shipped') || status.includes('picked up') || status.includes('dispatched')
}
const isDelivered = (order: Order) => `${order.fulfillmentStatus || ''} ${order.shopifyStatus || ''} ${order.tags.join(' ')}`.toLowerCase().includes('delivered')
const isNdr = (order: Order) => `${order.tags.join(' ')} ${order.shopifyStatus || ''}`.toLowerCase().includes('ndr')
const listStatus = (order: Order): OperationalStatus => (order.operationalStatus as OperationalStatus | null) || (
  isCancelled(order) ? 'Cancelled'
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
  const [notice, setNotice] = useState('')
  const [repeatIds, setRepeatIds] = useState<Set<string>>(new Set())
  const [callResult, setCallResult] = useState<CallResult>('No Answer')
  const [callComment, setCallComment] = useState('')
  const [nowTs, setNowTs] = useState(() => Date.now())
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
      setSelectedOrderId(current => current ?? data[0]?.internalId ?? null)
    } catch (err) {
      if ((err as Error).name !== 'AbortError') setError((err as Error).message)
    } finally {
      if (!signal?.aborted) setLoading(false)
    }
  }, [])

  useEffect(() => {
    const controller = new AbortController()
    const timeout = window.setTimeout(() => void loadOrders(controller.signal), 0)
    const interval = window.setInterval(() => void loadOrders(), 60_000)
    const clock = window.setInterval(() => setNowTs(Date.now()), 60_000)
    return () => {
      controller.abort()
      window.clearTimeout(timeout)
      window.clearInterval(interval)
      window.clearInterval(clock)
    }
  }, [loadOrders])

  const selectedOrder = useMemo(() => orders.find(order => order.internalId === selectedOrderId) || null, [orders, selectedOrderId])
  const queueOrders = useMemo(() => {
    const now = nowTs
    const sortedNewestFirst = (a: Order, b: Order) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
    const sortedOldestFirst = (a: Order, b: Order) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()
    const withinLast24Hours = (order: Order) => {
      const created = new Date(order.createdAt).getTime()
      return created <= now && created >= now - 24 * 60 * 60 * 1000
    }
    const olderThan24Hours = (order: Order) => new Date(order.createdAt).getTime() < now - 24 * 60 * 60 * 1000
    return {
      today: orders.filter(withinLast24Hours),
      previous: orders.filter(order => olderThan24Hours(order) && !isCancelled(order) && !isShipped(order) && !isDelivered(order)),
      ndr: orders.filter(isNdr),
      all: [...orders],
      sortedNewestFirst,
      sortedOldestFirst,
    }
  }, [orders, nowTs])

  useEffect(() => {
    if (!selectedOrder) return
    void (async () => {
      const ops = await getOrderOperations(selectedOrder.internalId)
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
    })().catch(() => setOperations(null))
  }, [selectedOrder])

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
    const created = new Date(order.createdAt).getTime()
    if (queue === 'today') return created <= nowTs && created >= nowTs - 24 * 60 * 60 * 1000
    if (queue === 'previous') return created < nowTs - 24 * 60 * 60 * 1000 && !isCancelled(order) && !isShipped(order) && !isDelivered(order)
    if (queue === 'ndr') return isNdr(order)
    return true
  }, [queue, nowTs])

  const filtered = useMemo(() => {
    let list = orders.filter(order => matchesSearch(order) && (payment === 'All payments' || order.payment === payment) && (risk === 'All risks' || order.risk === risk) && queuePredicate(order))
    list = queue === 'previous' ? list.sort((a, b) => new Date(a.createdAt).getTime() - new Date(b.createdAt).getTime()) : list.sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime())
    return list
  }, [orders, matchesSearch, payment, risk, queue, queuePredicate])

  const summaryCounts = useMemo(() => ({
    today: queueOrders.today.length,
    previous: queueOrders.previous.length,
    ndr: queueOrders.ndr.length,
    all: queueOrders.all.length,
  }), [queueOrders])

  const statusFromOrder = (order: Order): OperationalStatus => {
    return listStatus(order)
  }

  const callLog = [...(operations?.call_logs || [])].sort((a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime())
  const courierSyncMessage = operations?.courier_sync_error || operations?.courier_sync_status || 'Courier rates not connected'
  const status = selectedOrder ? statusFromOrder(selectedOrder) : 'Call Pending'
  const isRepeat = selectedOrder ? repeatIds.has(selectedOrder.internalId) : false
  const visibleCount = filtered.length
  const addressVerifiedLabel = operations?.address_verified
    ? `Address Verified by ${operations.address_verified_by || 'operator'} on ${operations.address_verified_at ? formatDateTime(operations.address_verified_at) : 'unknown time'}`
    : 'Address Verification Pending'

  const saveCallLog = async () => {
    if (!selectedOrder) return
    const updated = await addOrderCallLog(selectedOrder.internalId, {
      result: callResult,
      operator: 'Amit Kumar',
      comment: callComment,
    })
    setOperations(updated)
    setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, latestCallResult: updated.call_logs?.[0]?.result || null, operationalStatus: (updated.call_logs?.[0]?.result === 'Callback Requested' ? 'Callback Required' : updated.call_logs?.[0]?.result === 'Confirmed' ? (order.payment === 'Prepaid' && !updated.address_verified ? 'Address Verification Pending' : 'Ready for Booking') : updated.call_logs?.[0]?.result === 'Wrong Number' ? 'Needs Review' : updated.call_logs?.[0]?.result === 'Cancelled' ? 'Cancelled' : order.operationalStatus) as OperationalStatus | null, addressVerified: updated.address_verified, addressVerifiedAt: updated.address_verified_at, addressVerifiedBy: updated.address_verified_by, verifiedAddressSnapshot: updated.verified_address_snapshot, correctedAddress: updated.corrected_address, courierSyncStatus: updated.courier_sync_status, courierSyncError: updated.courier_sync_error } : order))
    setCallComment('')
    setNotice('Call attempt saved')
  }

  const saveAddress = async () => {
    if (!selectedOrder) return
    const updated = await saveOrderAddress(selectedOrder.internalId, {
      ...addressDraft,
      courier_sync_status: operations?.courier_sync_status || 'Not synchronized',
      courier_sync_error: operations?.courier_sync_error || null,
    })
    setOperations(updated)
    setOrders(prev => prev.map(order => order.internalId === selectedOrder.internalId ? { ...order, addressVerified: updated.address_verified, addressVerifiedAt: updated.address_verified_at, addressVerifiedBy: updated.address_verified_by, verifiedAddressSnapshot: updated.verified_address_snapshot, correctedAddress: updated.corrected_address, courierSyncStatus: updated.courier_sync_status, courierSyncError: updated.courier_sync_error, operationalStatus: (order.payment === 'Prepaid' ? 'Address Verification Pending' : order.operationalStatus) as OperationalStatus | null } : order))
    setNotice('Address saved')
  }

  const verifyAddress = async () => {
    if (!selectedOrder) return
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
    setNotice('Address verified')
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
          <button onClick={() => void loadOrders()} className="rounded-lg border border-slate-200 bg-white px-4 py-2.5 text-sm font-semibold text-slate-600 shadow-sm hover:bg-slate-50">Refresh</button>
        </div>

        <section className="mb-5 flex flex-wrap gap-2">
          {tabItems.map(tab => (
            <button key={tab.key} onClick={() => setQueue(tab.key)} className={`rounded-full px-4 py-2 text-sm font-medium ${queue === tab.key ? 'bg-slate-900 text-white' : 'bg-white text-slate-600 ring-1 ring-slate-200 hover:bg-slate-50'}`}>
              {tab.label}
              <span className={`ml-2 rounded-full px-2 py-0.5 text-[11px] font-bold ${queue === tab.key ? 'bg-white/15 text-white' : 'bg-slate-100 text-slate-500'}`}>{summaryCounts[tab.key]}</span>
            </button>
          ))}
        </section>

        <section className="overflow-hidden rounded-xl border border-slate-200 bg-white shadow-sm">
          <div className="flex flex-col gap-4 border-b border-slate-200 p-4 xl:flex-row xl:items-center xl:justify-between">
            <div className="relative min-w-0 flex-1 xl:max-w-sm">
              <span className="absolute left-3 top-3 text-slate-400"><Icon name="search" size={17} /></span>
              <input value={search} onChange={e => setSearch(e.target.value)} className="w-full rounded-lg border border-slate-200 py-2.5 pl-9 pr-3 text-sm outline-none placeholder:text-slate-400 focus:border-orange-300 focus:ring-2 focus:ring-orange-100" placeholder="Search by order or customer..." />
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Filter value={payment} onChange={setPayment} options={['All payments', 'COD', 'Prepaid']} />
              <Filter value={risk} onChange={setRisk} options={['All risks', 'High', 'Medium', 'Low']} />
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
                      {['Order No', 'Customer', 'Amount', 'Payment', 'Risk', 'Status', 'Actions'].map(column => <th key={column} className="whitespace-nowrap px-4 py-3.5">{column}</th>)}
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-slate-100">
                    {filtered.map(order => <OrderRow key={order.internalId} order={order} repeat={repeatIds.has(order.internalId)} onClick={() => setSelectedOrderId(order.internalId)} />)}
                  </tbody>
                </table>
                {filtered.length === 0 && <div className="py-14 text-center text-sm text-slate-400">No orders match your filters.</div>}
              </div>
              <div className="flex items-center justify-between border-t border-slate-200 px-4 py-3">
                <p className="text-xs text-slate-500">Showing <span className="font-semibold text-slate-700">{filtered.length}</span> of {orders.length} orders</p>
                <p className="text-xs text-slate-400">Rolling 24-hour queue and newest-first history.</p>
              </div>
            </>
          )}
        </section>
      </main>

      {selectedOrder && (
        <OrderDrawer
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
          courierSyncMessage={courierSyncMessage}
          addressVerificationLine={addressVerifiedLabel}
          onClose={() => setSelectedOrderId(null)}
          onSaveCallLog={() => void saveCallLog()}
          onSaveAddress={() => void saveAddress()}
          onVerifyAddress={() => void verifyAddress()}
        />
      )}

      {notice && <div className="fixed bottom-5 right-5 z-[60] rounded-lg bg-slate-900 px-4 py-3 text-sm font-medium text-white shadow-xl">{notice}</div>}
    </div>
  )
}

function Filter({ value, onChange, options }: { value: string; onChange: (value: string) => void; options: string[] }) {
  return <select value={value} onChange={e => onChange(e.target.value)} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium text-slate-600 outline-none focus:border-orange-300">{options.map(option => <option key={option}>{option}</option>)}</select>
}

function OrderRow({ order, repeat, onClick }: { order: Order; repeat: boolean; onClick: () => void }) {
  const statusText = listStatus(order)
  const status = statusText === 'Booked' || statusText === 'Shipped' || statusText === 'Delivered' ? 'bg-emerald-50 text-emerald-700' : statusText === 'Cancelled' || statusText === 'Needs Review' ? 'bg-rose-50 text-rose-700' : statusText === 'NDR' ? 'bg-violet-50 text-violet-700' : statusText === 'Address Verification Pending' || statusText === 'Call Pending' || statusText === 'Callback Required' ? 'bg-amber-50 text-amber-700' : 'bg-slate-100 text-slate-700'
  return (
    <tr onClick={onClick} className="cursor-pointer text-sm text-slate-600 hover:bg-orange-50/50">
      <td className="px-4 py-3.5 font-semibold text-slate-800">{order.orderNumber}</td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-2">
          {order.customerId && <span className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-bold ${repeat ? 'bg-violet-50 text-violet-700' : 'bg-slate-100 text-slate-600'}`}>{repeat ? '[RPT]' : '[NEW]'}</span>}
          <span className="font-medium text-slate-700">{order.customerName}</span>
        </div>
      </td>
      <td className="px-4 py-3.5 font-semibold text-slate-800">{formatMoney(order.amount)}</td>
      <td className="px-4 py-3.5"><span className={`rounded-md px-2 py-1 text-[11px] font-bold ${order.payment === 'COD' ? 'bg-amber-50 text-amber-700' : 'bg-emerald-50 text-emerald-700'}`}>{order.payment}</span></td>
      <td className="px-4 py-3.5"><span className={`rounded-md px-2 py-1 text-[11px] font-bold ring-1 ring-inset ${riskStyle[order.risk]}`}>{order.risk} Risk</span></td>
      <td className="px-4 py-3.5"><span className={`whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-bold ${status}`}>{statusText}</span></td>
      <td className="px-4 py-3.5">
        <div className="flex items-center gap-1">
          <button onClick={e => { e.stopPropagation(); onClick() }} className="rounded-md p-1.5 text-slate-400 hover:bg-slate-100 hover:text-slate-700"><Icon name="eye" size={16} /></button>
        </div>
      </td>
    </tr>
  )
}

function OrderDrawer({
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
  courierSyncMessage,
  addressVerificationLine,
  onClose,
  onSaveCallLog,
  onSaveAddress,
  onVerifyAddress,
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
  courierSyncMessage: string
  addressVerificationLine: string
  onClose: () => void
  onSaveCallLog: () => void
  onSaveAddress: () => void
  onVerifyAddress: () => void
}) {
  const shipping = order.shippingAmount == null ? 'Courier rates not connected' : formatMoney(order.shippingAmount)
  const verificationLine = addressVerificationLine
  const hasVerifiedAddress = verificationLine.startsWith('Address Verified by')
  const isPrepaid = order.payment === 'Prepaid'

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
            <div className="space-y-2 text-sm text-slate-600">
              <p>{courierSyncMessage}</p>
              <div className="rounded-lg border border-dashed border-slate-200 bg-slate-50 px-3 py-2 text-xs text-slate-500">Courier rates not connected. Booking and courier address editing will be enabled once courier APIs are connected.</div>
            </div>
          </Section>

          <Section title="Payment Breakup">
            <details>
              <summary className="cursor-pointer text-sm font-semibold text-slate-700">Collapsed by default</summary>
              <div className="mt-3 space-y-2 text-sm text-slate-500">
                <Line label="Order amount" value={formatMoney(order.amount)} />
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
          <button disabled title="Courier integration pending" className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-slate-200 px-3 py-2.5 text-sm font-semibold text-slate-500">
            <Icon name="truck" size={16} />
            Courier integration pending
          </button>
          <button className="rounded-lg border border-slate-200 p-2.5 text-slate-300"><Icon name="phone" size={17} /></button>
          <button className="rounded-lg border border-slate-200 p-2.5 text-slate-300"><Icon name="external" size={17} /></button>
          <button onClick={onClose} className="rounded-lg px-2 py-2.5 text-sm font-semibold text-slate-500 hover:bg-slate-50">Close</button>
        </footer>
      </aside>
    </div>
  )
}

function Field({ label, value, onChange }: { label: string; value: string; onChange: (value: string) => void }) {
  return (
    <label className="block">
      <span className="mb-1 block text-[10px] font-medium uppercase tracking-wide text-slate-400">{label}</span>
      <input value={value} onChange={e => onChange(e.target.value)} className="w-full rounded-lg border border-slate-200 px-3 py-2.5 text-sm outline-none focus:border-orange-300 focus:ring-2 focus:ring-orange-100" />
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
