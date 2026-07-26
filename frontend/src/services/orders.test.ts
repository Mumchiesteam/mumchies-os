import { afterEach, describe, expect, it, vi } from 'vitest'
import { getOrders } from './orders'

const response = (pageSize: number, total = 0) => new Response(JSON.stringify({
  items: [],
  page: 1,
  page_size: pageSize,
  total,
  total_pages: Math.max(1, Math.ceil(total / pageSize)),
}), { status: 200, headers: { 'Content-Type': 'application/json' } })

afterEach(() => vi.restoreAllMocks())

describe('orders pagination client', () => {
  it('requests the default 20-row first page and preserves totals', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(20, 41))
    const result = await getOrders()
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('page')).toBe('1')
    expect(url.searchParams.get('page_size')).toBe('20')
    expect(result).toMatchObject({ page: 1, pageSize: 20, total: 41, totalPages: 3 })
  })

  it.each([50, 100] as const)('requests %i rows per page', async pageSize => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(pageSize))
    await getOrders({ page: 2, pageSize })
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('page')).toBe('2')
    expect(url.searchParams.get('page_size')).toBe(String(pageSize))
  })

  it('sends Printed Today as a clickable queue selection', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(response(20))
    await getOrders({ queue: 'printed_today', page: 1 })
    const url = new URL(String(fetchMock.mock.calls[0][0]))
    expect(url.searchParams.get('queue')).toBe('printed_today')
  })
})
