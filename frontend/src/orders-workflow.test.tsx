import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { COD_WHATSAPP_MESSAGE, MultilineField, callResults, indianWhatsAppNumber } from './App'

describe('Orders COD workflow', () => {
  it('uses editable, full-width wrapped multiline address fields without horizontal scrolling', () => {
    const changed = vi.fn()
    const html = renderToStaticMarkup(<MultilineField label="Address Line 1" value={'Long address '.repeat(20)} onChange={changed} />)
    expect(html).toContain('<textarea')
    expect(html).toContain('sm:col-span-2')
    expect(html).toContain('overflow-x-hidden')
    expect(html).toContain('whitespace-pre-wrap')
    expect(html).toContain('Long address')
  })

  it('offers only canonical new COD outcomes while retaining historical rendering as strings', () => {
    expect(callResults).toEqual(['Confirmed', 'No Answer', 'Busy', 'Switched Off', 'On Hold', 'Cancelled'])
    expect(callResults).not.toContain('Callback Requested' as never)
    expect(callResults).not.toContain('Wrong Number' as never)
  })

  it('normalizes valid Indian numbers and encodes the complete WhatsApp message', () => {
    expect(indianWhatsAppNumber('+91 98765-43210')).toBe('919876543210')
    expect(indianWhatsAppNumber('09876543210')).toBe('919876543210')
    expect(indianWhatsAppNumber('123')).toBeNull()
    expect(decodeURIComponent(encodeURIComponent(COD_WHATSAPP_MESSAGE))).toBe(COD_WHATSAPP_MESSAGE)
    expect(COD_WHATSAPP_MESSAGE).toContain('Please reply CONFIRM')
  })
})
