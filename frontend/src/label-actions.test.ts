import { describe, expect, it } from 'vitest'
import appSource from './App.tsx?raw'
import ordersSource from './services/orders.ts?raw'

describe('booked shipment label actions', () => {
  it('makes the normalized 4x6 label primary and provider original secondary', () => {
    expect(appSource).toContain("retrieveLabel('print_4x6')")
    expect(appSource).toContain('Print 4×6 Label')
    expect(appSource).toContain("retrieveLabel('original')")
    expect(appSource).toContain('Open Original Label')
    expect(appSource).not.toContain('Download 4×6 Label')
    expect(appSource).not.toContain('Open / Print Label')
  })

  it('requests print_ready only for the normalized action', () => {
    expect(appSource).toContain("action === 'print_4x6'")
    expect(ordersSource).toContain('print_ready=${printReady}')
  })
})
