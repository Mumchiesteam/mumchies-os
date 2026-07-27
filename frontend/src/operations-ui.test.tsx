import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import App from './App'

describe('operations-first Orders layout', () => {
  it('renders only the required top navigation and daily operation menus', () => {
    const html = renderToStaticMarkup(<App />)
    for (const item of ['Dashboard', 'Orders', 'NDR', 'Reconciliation', 'Fresh Orders', 'Previous Pending Orders', 'Labels to Print', 'Printed Today']) {
      expect(html).toContain(item)
    }
    for (const removed of ['Customers', 'Reports', 'Settings', 'All Orders', 'Awaiting Confirmation', 'Shiprocket Cleanup Pending']) {
      expect(html).not.toContain(`>${removed}<`)
    }
  })

  it('keeps only the operational filters and Engage table column', () => {
    const html = renderToStaticMarkup(<App />)
    for (const filter of ['Payment Type', 'Risk', 'Sort']) expect(html).toContain(`aria-label="${filter}"`)
    for (const removed of ['aria-label="Order Confirmation"', 'aria-label="Address Verification"', 'aria-label="COD → Prepaid"']) expect(html).not.toContain(removed)
  })
})
