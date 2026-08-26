export type QueueDatePreset = 'all' | 'today' | 'yesterday' | 'last_7_days' | 'custom'
export type QueueDateFilter = { preset: QueueDatePreset; start: string; end: string }
export type DispatchDateStage = 'ready_to_ship' | 'manifested'

const startOfDay = (value: Date) => new Date(value.getFullYear(), value.getMonth(), value.getDate())

export function matchesQueueDate(value: string | null | undefined, filter: QueueDateFilter, now = new Date()): boolean {
  if (filter.preset === 'all') return true
  if (!value) return false
  const timestamp = new Date(value)
  if (Number.isNaN(timestamp.getTime())) return false
  const today = startOfDay(now)
  if (filter.preset === 'today') return timestamp >= today
  if (filter.preset === 'yesterday') {
    const yesterday = new Date(today); yesterday.setDate(yesterday.getDate() - 1)
    return timestamp >= yesterday && timestamp < today
  }
  if (filter.preset === 'last_7_days') {
    const start = new Date(today); start.setDate(start.getDate() - 6)
    return timestamp >= start
  }
  const start = filter.start ? new Date(`${filter.start}T00:00:00`) : null
  const end = filter.end ? new Date(`${filter.end}T00:00:00`) : null
  if (end) end.setDate(end.getDate() + 1)
  return (!start || timestamp >= start) && (!end || timestamp < end)
}

export function matchesOrderQueueFilters(order: { createdAt: string; payment: string; risk: string }, dateFilter: QueueDateFilter, payment: string, risk: string, now = new Date()): boolean {
  return matchesQueueDate(order.createdAt, dateFilter, now)
    && (payment === 'All' || order.payment === payment)
    && (risk === 'All' || order.risk === risk)
}

export function dispatchQueueDate(row: { booked_at?: string | null; manifested_at?: string | null }, stage: DispatchDateStage): string | null | undefined {
  return stage === 'manifested' ? row.manifested_at : row.booked_at
}
