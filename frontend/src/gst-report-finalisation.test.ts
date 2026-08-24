import { describe, expect, it } from 'vitest'

import pageSource from './components/ReportsPage.tsx?raw'
import serviceSource from './services/reports.ts?raw'

describe('GST report finalisation workflow', () => {
  it('shows draft/final states and requires confirmation', () => {
    for (const text of ['DRAFT', 'FINAL', 'Finalise Report', 'Download Final CSV', 'Regenerate Draft', 'Cancel']) expect(pageSource).toContain(text)
    expect(pageSource).toContain('Future Shopify changes will not alter this saved report.')
    expect(pageSource).toContain('report.can_finalise')
  })

  it('loads saved months separately and regenerates drafts explicitly', () => {
    expect(pageSource).toContain('getFinalGstReport(month)')
    expect(pageSource).toContain('regenerate: true')
    expect(serviceSource).toContain('/api/v1/reports/gst/final?')
    expect(serviceSource).toContain('/api/v1/reports/gst/finalise')
  })

  it('shows all required comparison metrics', () => {
    for (const field of ['delivered_orders', 'taxable_value', 'cgst', 'sgst', 'igst', 'total_gst', 'gross_sales']) expect(pageSource).toContain(field)
  })
})
