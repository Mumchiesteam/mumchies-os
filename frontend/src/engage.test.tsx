import { renderToStaticMarkup } from 'react-dom/server'
import { describe, expect, it } from 'vitest'

import { EngageCircle } from './components/EngageStatus'
import { engageCategory } from './utils/engage'

describe('Engage status rendering', () => {
  it.each([
    [0, 'pending'], ['0', 'pending'], [1, 'pending'], ['1', 'pending'],
    [2, 'successful'], ['2', 'successful'], [21, 'successful'], ['21', 'successful'],
    [3, 'cancelled'], ['3', 'cancelled'], [6, 'disabled'], ['6', 'disabled'],
    ['NA', 'disabled'], ['future', 'unknown'],
  ])('classifies raw value %s as %s', (value, expected) => {
    expect(engageCategory(value)).toBe(expected)
  })

  it.each([
    ['1', 'bg-amber-400'], ['2', 'bg-emerald-500'], ['21', 'bg-emerald-500'],
    ['3', 'bg-rose-500'], ['6', 'bg-slate-300'], ['NA', 'bg-slate-300'],
  ])('renders raw value %s with %s', (value, expectedClass) => {
    const html = renderToStaticMarkup(<EngageCircle label="OC" stageName="Order Confirmation" value={value} message="Exact Shiprocket message" />)
    expect(html).toContain(expectedClass)
    expect(html).toContain('Exact Shiprocket message')
  })

  it('renders an accessible tooltip with stage, exact message, and raw value', () => {
    const html = renderToStaticMarkup(<EngageCircle label="OC" stageName="Order Confirmation" value="0" message="Awaiting customer response" />)
    expect(html).toContain('Order Confirmation')
    expect(html).toContain('Awaiting customer response')
    expect(html).toContain('Raw value: 0')
    expect(html).not.toContain('unknown status')
  })

  it('renders unknown values neutrally with a warning without crashing', () => {
    const html = renderToStaticMarkup(<EngageCircle label="CP" stageName="COD to Prepaid" value={{ future: true }} message="Future status" />)
    expect(html).toContain('bg-slate-300')
    expect(html).toContain('Warning: Unknown Engage value')
    expect(html).toContain('unknown status')
    expect(html).toContain('{&quot;future&quot;:true}')
  })
})
