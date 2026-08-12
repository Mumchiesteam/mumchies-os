import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NDRPage } from './components/NDRPage'
import { actOnNDR, getNDRCases, type NDRSummary } from './services/ndr'
import { kpiButtonClass, shopifyPresentation, toggleKpi } from './utils/ndrView'

afterEach(() => vi.restoreAllMocks())

describe('NDR operations module', () => {
  it('renders dashboard, filters, grid columns and import-only refresh', () => {
    const html = renderToStaticMarkup(<NDRPage />)
    for (const text of ['NDR Dashboard','Refresh Data','Last successful import','Search order, AWB, customer or phone','Priority','Order Number','AWB','Product','Customer','Phone','Courier','Current Status','Failure Reason','Recommended Action','Ageing','Last Update','Actions']) expect(html).toContain(text)
    expect(html).not.toContain('Assigned To')
    expect(html).not.toContain('Sync Now')
  })
  it('uses only the persisted action endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await actOnNDR('case-1', { action:'resolve', note:'Done' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/ndr/cases/case-1/actions')
    expect(String(fetchMock.mock.calls[0][0])).not.toContain('/ndr/sync')
  })
  it('sends grid filters to the backend', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async()=>new Response(JSON.stringify({items:[],total:0}), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await getNDRCases({ courier:'shadowfax', priority:'high', status:'new' })
    const url = new URL(String(fetchMock.mock.calls[0][0])); expect(url.searchParams.get('courier')).toBe('shadowfax'); expect(url.searchParams.get('priority')).toBe('high')
  })
  it('sends every KPI filter to the backend across the full result set', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockImplementation(async()=>new Response(JSON.stringify({items:[],total:0}), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    for (const kpi of ['active','new_today','awaiting_customer','courier_pending','resolved_today','over_sla'] as const) await getNDRCases({kpi})
    expect(fetchMock.mock.calls.map(call=>new URL(String(call[0])).searchParams.get('kpi'))).toEqual(['active','new_today','awaiting_customer','courier_pending','resolved_today','over_sla'])
  })
  it('combines KPI, courier and search filters', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({items:[],total:0}), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await getNDRCases({kpi:'over_sla',courier:'delhivery',search:'323500'})
    const query=new URL(String(fetchMock.mock.calls[0][0])).searchParams
    expect(Object.fromEntries(query)).toMatchObject({kpi:'over_sla',courier:'delhivery',search:'323500'})
  })
  it('toggles a selected KPI and gives selected cards highlighted styling', () => {
    expect(toggleKpi(undefined,'active')).toBe('active')
    expect(toggleKpi('active','active')).toBeUndefined()
    expect(toggleKpi('active','over_sla')).toBe('over_sla')
    expect(kpiButtonClass(true)).toContain('border-orange-400')
    expect(kpiButtonClass(false)).not.toContain('border-orange-400')
  })
  it('shows Shopify API source without a stale GDrive warning', () => {
    const result=shopifyPresentation(summary({source:'api'},['GDrive Shopify CSV is 8 days old']))
    expect(result).toMatchObject({matchText:'33/39 matched',sourceLabel:'API',visibleWarnings:[]})
  })
  it('shows GDrive fallback and its stale warning only for that source', () => {
    const result=shopifyPresentation(summary({source:'gdrive_csv'},['GDrive Shopify CSV is 8 days old']))
    expect(result.sourceLabel).toBe('GDrive fallback')
    expect(result.visibleWarnings).toEqual(['GDrive Shopify CSV is 8 days old'])
  })
  it('uses null-safe Shopify fallbacks', () => {
    const result=shopifyPresentation(summary(undefined,undefined,false))
    expect(`${result.matchText} ${result.sourceLabel} ${result.visibleWarnings.join(' ')}`).not.toMatch(/undefined|\[object Object\]/)
    expect(result.matchText).toBe('Unavailable')
  })
})

function summary(shopify?:Record<string,unknown>, warnings?:string[], includeCounts=true):NDRSummary {
  return {
    active_ndr:1,new_today:1,awaiting_customer:0,courier_pending:0,resolved_today:0,over_sla:0,last_sync_at:null,last_sync_status:'completed',
    source_counts:includeCounts?{phones_matched:33,phones_total:39}:null,
    source_health:shopify||warnings?{shopify:{status:'success',phones_matched:33,phones_total:39,...shopify},...(warnings?{warnings}:{})}:null,
  }
}
