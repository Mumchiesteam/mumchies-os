import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AnalyticsPage } from './components/AnalyticsPage'
import { TrackingPollerHealthView } from './components/TrackingPollerHealth'
import type { PollerHealth } from './services/poller-health'

const data: PollerHealth = {
  enabled: true,
  audit: {
    latest_runs: [{ run_id: 'run-1', started_at: '2026-08-10T19:17:24Z', completed_at: '2026-08-10T19:18:34Z', total_attempted: 50, total_succeeded: 38, total_failed: 12, new_events_persisted: 3, provider_counts: { shiprocket: { attempted: 30, succeeded: 20, failed: 10, new_events: 2 }, delhivery: { attempted: 20, succeeded: 18, failed: 2, new_events: 1 } }, status: 'completed' }],
    provider_coverage: {}, failure_breakdown: { not_found: 7, timeout: 5 }, event_count_by_provider: { shiprocket: 150, delhivery: 40 }, lifecycle_coverage: { shiprocket: { delivered: 20, ndr: 3 }, delhivery: { in_transit: 10 } },
    failed_shipments: [{ run_id: 'run-1', order_id: 'gid-1', order_number: '324000', provider: 'shiprocket', courier_service: 'Delhivery Surface', awb_reference: 'AWB-1', error_category: 'not_found', http_status: 404 }],
  },
}

describe('Tracking Poller Health', () => {
  it('renders compact retained run, provider, failure and lifecycle diagnostics', () => {
    const html = renderToStaticMarkup(<TrackingPollerHealthView data={data} />)
    for (const text of ['Tracking Poller Health', '50', '38', '12', '76.0%', 'Shiprocket', 'Delhivery', 'Not Found', '324000', 'AWB-1', '404', 'Delivered', 'Ndr']) expect(html).toContain(text)
  })
  it('is omitted from Analytics unless privileged', () => {
    expect(renderToStaticMarkup(<AnalyticsPage />)).not.toContain('Tracking Poller Health')
    expect(renderToStaticMarkup(<AnalyticsPage showDiagnostics />)).toContain('Tracking Poller Health')
  })
})
