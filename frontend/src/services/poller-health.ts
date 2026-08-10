import { apiBase, apiFetch } from './orders'

export type PollerProviderStats = { attempted: number; succeeded: number; failed: number; new_events?: number }
export type PollerFailure = {
  run_id: string; order_id: string | null; order_number: string | null; provider: string
  courier_service: string | null; awb_reference: string | null; error_category: string | null
  http_status: number | null; error_summary?: string | null
}
export type PollerRun = {
  run_id: string; started_at: string; completed_at: string | null; total_attempted: number
  total_succeeded: number; total_failed: number; new_events_persisted: number
  provider_counts: Record<string, PollerProviderStats>; status: string
}
export type PollerHealth = {
  enabled: boolean; last_poll_started?: string | null; last_poll_completed?: string | null
  shipments_attempted?: number; shipments_succeeded?: number; shipments_failed?: number
  new_events_persisted?: number; provider_stats?: Record<string, PollerProviderStats>
  audit: {
    latest_runs: PollerRun[]; provider_coverage: Record<string, PollerProviderStats & { success_percent?: number }>
    failure_breakdown: Record<string, number>; failed_shipments: PollerFailure[]
    event_count_by_provider: Record<string, number>; lifecycle_coverage: Record<string, Record<string, number>>
  }
}

export async function getPollerHealth(): Promise<PollerHealth> {
  const response = await apiFetch(`${apiBase}/api/v1/couriers/poller/status`)
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new Error(body?.detail || 'Could not load tracking poller health.')
  return body
}
