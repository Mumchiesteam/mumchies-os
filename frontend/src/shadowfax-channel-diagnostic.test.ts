import { afterEach, describe, expect, it, vi } from 'vitest'
import { inspectShadowfaxShopifyOrder } from './services/orders'

afterEach(() => vi.restoreAllMocks())

describe('Shadowfax Shopify channel-order diagnostic', () => {
  it('uses the authenticated OS API client read-only endpoint for the open order', async () => {
    const fetchMock = vi.spyOn(globalThis, 'fetch').mockResolvedValue(new Response(JSON.stringify({ resolver_result: { found: true } }), { status: 200, headers: { 'Content-Type': 'application/json' } }))
    await inspectShadowfaxShopifyOrder('6902274883662')
    expect(String(fetchMock.mock.calls[0][0])).toContain('/api/v1/shadowfax/shopify-order-diagnostic/6902274883662')
    expect(fetchMock.mock.calls[0][1]).toMatchObject({ credentials: 'include' })
  })
})
