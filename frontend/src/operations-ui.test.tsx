import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import App, { OrdersTable } from './App'
import { displayedOrderNumber, orderNumberClipboardValue, stopCopyPropagation } from './utils/orderNumber'

describe('operations-first Orders layout', () => {
  it('renders only the required top navigation and daily operation menus', () => {
    const html = renderToStaticMarkup(<App />)
    for (const item of ['Dashboard', 'Orders', 'NDR', 'Reconciliation', 'Reports', 'Fresh Orders', 'Previous Pending Orders', 'Ready to Ship', 'Manifested']) {
      expect(html).toContain(item)
    }
    for (const removed of ['Customers', 'Settings', 'All Orders', 'Awaiting Confirmation', 'Shiprocket Cleanup Pending']) {
      expect(html).not.toContain(`>${removed}<`)
    }
    expect(html).not.toContain('Pending Booking')
  })

  it('keeps only the operational filters and Engage table column', () => {
    const html = renderToStaticMarkup(<App />)
    for (const filter of ['Payment Type', 'Risk', 'Sort']) expect(html).toContain(`aria-label="${filter}"`)
    for (const removed of ['aria-label="Order Confirmation"', 'aria-label="Address Verification"', 'aria-label="COD → Prepaid"']) expect(html).not.toContain(removed)
  })

  it('keeps the displayed hash while excluding it from copied order numbers', () => {
    expect(displayedOrderNumber('323791')).toBe('#323791')
    expect(displayedOrderNumber('#323791')).toBe('#323791')
    expect(orderNumberClipboardValue('#323791')).toBe('323791')
    expect(orderNumberClipboardValue('323791')).toBe('323791')
  })

  it('removes the entire summary-card block while preserving queues, filters and table', () => {
    const html = renderToStaticMarkup(<App />)
    for (const card of ['New Orders', 'High Risk', 'Repeat Customers']) expect(html).not.toContain(card)
    expect(html.match(/>COD</g)).toHaveLength(1)
    expect(html.match(/>Prepaid</g)).toHaveLength(1)
    for (const queue of ['Fresh Orders', 'Previous Pending Orders', 'Ready to Ship', 'Manifested']) expect(html).toContain(queue)
    for (const filter of ['Payment Type', 'Risk', 'Sort']) expect(html).toContain(`aria-label="${filter}"`)
    const table = renderToStaticMarkup(<OrdersTable orders={[]} repeatIds={new Set()} onOpen={() => undefined} emptyMessage="No orders" />)
    expect(table).toContain('Order No')
  })

  it('keeps table copy clicks isolated from the drawer row', () => {
    const stopPropagation = vi.fn()
    stopCopyPropagation({ stopPropagation }, true)
    expect(stopPropagation).toHaveBeenCalledOnce()
  })
})
