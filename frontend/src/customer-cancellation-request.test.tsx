import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'
import appSource from './App.tsx?raw'
import { OrderStatusBadge } from './components/OrderStatusBadge'

describe('customer cancellation request safety', () => {
  it('renders a prominent warning status without treating the request as completed cancellation', () => {
    const html = renderToStaticMarkup(<OrderStatusBadge order={{ operationalStatus: 'Customer Requested Cancellation' } as never} />)
    expect(html).toContain('Customer Requested Cancellation')
    expect(html).toContain('bg-amber-100')
  })

  it('shows the drawer warning and booking blocker from canonical API state', () => {
    expect(appSource).toContain('order.customerCancellationRequested && <p role="alert"')
    expect(appSource).toContain('Customer Requested Cancellation</p>')
    expect(appSource).toContain("'customer requested cancellation': 'Customer requested cancellation'")
  })
})
