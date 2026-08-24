import { apiBase, apiFetch } from './orders'

export type GstReportRow = {
  'Place of Supply': string
  'GST Rate': string
  Orders: number
  'Taxable Value': number
  CGST: number
  SGST: number
  IGST: number
  'Total Invoice Value': number
}

export type GstReport = {
  status: 'DRAFT' | 'FINAL'
  finalised_at: string | null
  methodology_version: string
  checksum: string
  can_finalise: boolean
  finalisation_failures: string[]
  month: string
  summary: {
    delivered_orders: number
    raw_delivered_orders: number
    excluded_orders: number
    gross_sales: number
    taxable_value: number
    cgst: number
    sgst: number
    igst: number
    total_gst: number
    exceptions: number
  }
  rows: GstReportRow[]
  exceptions: { order_number: string; reason: string; invoice_value: number; delivered_date: string }[]
  reconciliation: {
    previous_month_created_delivered: { orders: number; value: number }
    selected_month_created_delivered_following: { orders: number; value: number }
  }
  adjustments: { original_shopify_gst: number; shipping_gst: number; product_gst_corrections: number }
  baseline_comparison: { matches: boolean; differences: Record<string, number> } | null
  population: {
    raw_delivered_order_numbers: string[]
    filing_eligible_order_numbers: string[]
    excluded_order_numbers: string[]
  }
  comparison_to_final: null | {
    matches: boolean
    fields: Record<string, { final: number; draft: number; difference: number }>
  }
  final_reference?: { finalised_at: string; checksum: string } | null
}

export async function getGstReport(month: string, options: { refresh?: boolean; regenerate?: boolean } = {}): Promise<GstReport> {
  const params = new URLSearchParams({ month })
  if (options.refresh) params.set('refresh', 'true')
  if (options.regenerate) params.set('regenerate', 'true')
  const response = await apiFetch(`${apiBase}/api/v1/reports/gst?${params.toString()}`)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || 'Could not generate the GST report.')
  }
  return response.json()
}

export async function getFinalGstReport(month: string): Promise<GstReport | null> {
  const response = await apiFetch(`${apiBase}/api/v1/reports/gst/final?month=${encodeURIComponent(month)}`)
  if (!response.ok) throw new Error('Could not check the saved GST report.')
  const body = await response.json()
  return body.exists ? body.report : null
}

export async function finaliseGstReport(month: string, checksum: string): Promise<GstReport> {
  const response = await apiFetch(`${apiBase}/api/v1/reports/gst/finalise`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ month, checksum }),
  })
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || 'Could not finalise the GST report.')
  }
  return response.json()
}

export function gstReportDownloadUrl(month: string): string {
  return `${apiBase}/api/v1/reports/gst/export?month=${encodeURIComponent(month)}`
}
