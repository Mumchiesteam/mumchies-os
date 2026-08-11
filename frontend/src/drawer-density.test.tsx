import { describe, expect, it } from 'vitest'
import appSource from './App.tsx?raw'

describe('order drawer density', () => {
  it('keeps customer and address controls compact without removing their content', () => {
    expect(appSource).toContain('grid grid-cols-2 gap-2 text-sm leading-snug')
    expect(appSource).toContain('rows={1}')
    expect(appSource).toContain('min-h-[42px]')
    expect(appSource).toContain('resize-y overflow-x-hidden whitespace-pre-wrap break-words')
  })

  it('places address verification beside the section heading', () => {
    expect(appSource).toContain('<Section title="Shipping Address" subtitle=')
    expect(appSource).not.toContain('mb-3 rounded-lg border border-slate-100 bg-slate-50 px-3 py-2 text-sm text-slate-600')
  })

  it('uses compact courier spacing and a responsive shipment summary', () => {
    expect(appSource).toContain('<div className="space-y-1.5">')
    expect(appSource).toContain('w-full rounded-xl border p-2.5 text-left transition')
    expect(appSource).toContain('gap-x-4 gap-y-1 rounded-lg border border-emerald-100')
    expect(appSource).toContain('sm:grid-cols-2')
  })
})
