import type { Order } from '../services/orders'
import { listStatus } from '../utils/orderStatus'

export function OrderStatusBadge({ order }: { order: Order }) {
  const status = listStatus(order)
  const style = status === 'Booked' || status === 'Shipped' || status === 'Delivered'
    ? 'bg-emerald-50 text-emerald-700'
    : status === 'Cancelled' || status === 'Needs Review'
      ? 'bg-rose-50 text-rose-700'
      : status === 'NDR'
        ? 'bg-violet-50 text-violet-700'
        : status === 'Address Verification Pending' || status === 'Call Pending' || status === 'Callback Required'
          ? 'bg-amber-50 text-amber-700'
          : 'bg-slate-100 text-slate-700'
  return <span className={`whitespace-nowrap rounded-md px-2 py-1 text-[11px] font-bold ${style}`}>{status}</span>
}
