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
}

export async function getGstReport(month: string, refresh = false): Promise<GstReport> {
  const params = new URLSearchParams({ month })
  if (refresh) params.set('refresh', 'true')
  const response = await apiFetch(`${apiBase}/api/v1/reports/gst?${params.toString()}`)
  if (!response.ok) {
    const body = await response.json().catch(() => null)
    throw new Error(body?.detail || 'Could not generate the GST report.')
  }
  return response.json()
}

export function gstReportDownloadUrl(month: string): string {
  return `${apiBase}/api/v1/reports/gst/export?month=${encodeURIComponent(month)}`
}
