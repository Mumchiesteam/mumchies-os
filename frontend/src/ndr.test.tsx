import { renderToStaticMarkup } from 'react-dom/server'
import { afterEach, describe, expect, it, vi } from 'vitest'
import { NDRPage } from './components/NDRPage'
import { actOnNDR, getNDRCases, syncNDR } from './services/ndr'

afterEach(() => vi.restoreAllMocks())

describe('NDR operations module', () => {
  it('renders dashboard, filters, grid columns and manual sync', () => {
    const html = renderToStaticMarkup(<NDRPage />)
    for (const text of ['NDR Dashboard','Sync Now','Search order, AWB, customer or phone','Priority','Order Number','AWB','Failure Reason','Recommended Action','Assigned To','Actions']) expect(html).toContain(text)
  })
  it('uses one batch sync endpoint and persisted action endpoint', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response('{}', { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await syncNDR(); await actOnNDR('case-1', { action:'resolve', note:'Done' })
    expect(String(fetchMock.mock.calls[0][0])).toContain('/ndr/sync')
    expect(String(fetchMock.mock.calls[1][0])).toContain('/ndr/cases/case-1/actions')
  })
  it('sends grid filters to the backend', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({items:[],total:0}), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await getNDRCases({ courier:'shadowfax', priority:'high', status:'new' })
    const url = new URL(String(fetchMock.mock.calls[0][0])); expect(url.searchParams.get('courier')).toBe('shadowfax'); expect(url.searchParams.get('priority')).toBe('high')
  })
})
