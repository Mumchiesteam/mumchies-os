import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import { AnalyticsPage } from './components/AnalyticsPage'
import { PeriodSelector } from './components/PeriodSelector'
import { analyticsKpis } from './services/analytics'

describe('Analytics', () => {
  it('defaults to Last 30 Days and renders all shared period choices', () => {
    const html = renderToStaticMarkup(<AnalyticsPage />)
    for (const label of ['Today', 'Yesterday', 'Last 7 Days', 'Month to Date', 'Last 30 Days', 'Custom']) expect(html).toContain(label)
    expect(html).toContain('Business performance')
    const labels = analyticsKpis.map(([, label]) => label)
    for (const label of ['Total Orders', 'Active Orders', 'Order Value', 'Items / Order', 'Fulfilled Orders', 'Fulfilment']) expect(labels).toContain(label)
    expect(labels).not.toContain('Revenue')
  })
  it('renders custom from and to controls through the shared selector', () => {
    const html = renderToStaticMarkup(<PeriodSelector prefix="Analytics" preset="custom" start="2026-06-01" end="2026-06-30" onChange={() => undefined}/>)
    expect(html).toContain('Analytics from date'); expect(html).toContain('Analytics to date')
  })
})
