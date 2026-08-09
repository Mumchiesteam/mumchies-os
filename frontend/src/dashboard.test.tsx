import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'
import { DashboardPage } from './components/DashboardPage'
import { workspaceLoadsForPage } from './App'
import { getDashboard } from './services/dashboard'

describe('management dashboard', () => {
  it('renders the common period controls compactly', () => {
    const html = renderToStaticMarkup(<DashboardPage onNavigate={() => undefined} />)
    for (const label of ['Today', 'Yesterday', 'Last 7 Days', 'Month to Date', 'Last 30 Days', 'Custom']) expect(html).toContain(label)
    expect(html).toContain('Loading dashboard')
  })

  it('sends custom dates to the dashboard API', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({}), { status: 200 }))
    await getDashboard('custom', '2026-06-01', '2026-06-30')
    const query = new URL(String(fetchMock.mock.calls[0][0])).searchParams
    expect(Object.fromEntries(query)).toMatchObject({ preset: 'custom', start: '2026-06-01', end: '2026-06-30' })
  })

  it('does not start hidden Orders or Reconciliation provider loads on Dashboard', () => {
    expect(workspaceLoadsForPage('Dashboard')).toEqual({ orders: false, reconciliation: false })
    expect(workspaceLoadsForPage('Orders')).toEqual({ orders: true, reconciliation: false })
    expect(workspaceLoadsForPage('Reconciliation')).toEqual({ orders: false, reconciliation: true })
  })
})
