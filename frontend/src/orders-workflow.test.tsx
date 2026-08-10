import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it, vi } from 'vitest'

import { COD_WHATSAPP_MESSAGE, MultilineField, callResultLabel, callResults, codWhatsAppUrl, indianWhatsAppNumber, shouldShowCodWhatsApp } from './App'
import { selectAllLabelIds, selectAllLabelState } from './utils/labelSelection'

describe('Orders COD workflow', () => {
  it('uses editable, full-width wrapped multiline address fields without horizontal scrolling', () => {
    const changed = vi.fn()
    for (const label of ['Address Line 1', 'Address Line 2']) {
      const value = `${label}: ${'Long address '.repeat(20)}`
      const html = renderToStaticMarkup(<MultilineField label={label} value={value} onChange={changed} />)
      expect(html).toContain('<textarea')
      expect(html).toContain('sm:col-span-2')
      expect(html).toContain('overflow-x-hidden')
      expect(html).toContain('whitespace-pre-wrap')
      expect(html).toContain(value)
      expect(html).not.toContain('ellipsis')
    }
  })

  it('offers only canonical new COD outcomes while retaining historical rendering as strings', () => {
    expect(callResults).toEqual(['Confirmed', 'No Answer', 'Busy', 'Switched Off', 'On Hold', 'Cancelled'])
    expect(callResults).not.toContain('Callback Requested' as never)
    expect(callResults).not.toContain('Wrong Number' as never)
    expect(callResultLabel('Cancelled')).toBe('Cancel')
    expect(callResults).toContain('Cancelled')
  })

  it('normalizes valid Indian numbers and encodes the complete WhatsApp message', () => {
    expect(indianWhatsAppNumber('+91 98765-43210')).toBe('919876543210')
    expect(indianWhatsAppNumber('09876543210')).toBe('919876543210')
    expect(indianWhatsAppNumber('123')).toBeNull()
    expect(decodeURIComponent(encodeURIComponent(COD_WHATSAPP_MESSAGE))).toBe(COD_WHATSAPP_MESSAGE)
    expect(COD_WHATSAPP_MESSAGE).toContain('Please reply CONFIRM')
    const url = codWhatsAppUrl('+91 98765-43210')
    expect(url).toBe(`https://wa.me/919876543210?text=${encodeURIComponent(COD_WHATSAPP_MESSAGE)}`)
    expect(new URL(url!).searchParams.get('text')).toBe(COD_WHATSAPP_MESSAGE)
  })

  it.each(['No Answer', 'Busy', 'Switched Off'])('shows WhatsApp for %s', result => {
    expect(shouldShowCodWhatsApp('cod', result)).toBe(true)
  })

  it.each(['Confirmed', 'On Hold', 'Cancelled'])('hides WhatsApp for %s', result => {
    expect(shouldShowCodWhatsApp('cod', result)).toBe(false)
  })

  it('hides WhatsApp for prepaid orders', () => {
    expect(shouldShowCodWhatsApp('prepaid', 'No Answer')).toBe(false)
  })
})

describe('Labels Select All', () => {
  const all = [
    { order_id: '1', provider: 'shiprocket' },
    { order_id: '2', provider: 'shiprocket' },
    { order_id: '3', provider: 'delhivery' },
  ]

  it('selects the first displayed provider only when none is selected', () => {
    expect([...selectAllLabelIds(all, all, new Set(), true)]).toEqual(['1', '2'])
  })

  it('selects only displayed labels for the current provider', () => {
    const selected = selectAllLabelIds(all, [all[1], all[2]], new Set(['1']), true)
    expect([...selected]).toEqual(['1', '2'])
  })

  it('deselects all displayed labels without changing filtered-out selections', () => {
    const selected = selectAllLabelIds(all, [all[1], all[2]], new Set(['1', '2', '3']), false)
    expect([...selected]).toEqual(['1'])
  })

  it('reports checked and indeterminate state for displayed eligible labels', () => {
    expect(selectAllLabelState(all, all, new Set(['1']))).toEqual({ checked: false, indeterminate: true, eligible: 2 })
    expect(selectAllLabelState(all, all, new Set(['1', '2']))).toEqual({ checked: true, indeterminate: false, eligible: 2 })
  })
})
