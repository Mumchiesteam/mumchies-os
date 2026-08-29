export type DrawerIdentity = { orderId: string; generation: number }
export type DrawerQuoteIdentity = DrawerIdentity & { contextKey: string }

export const emptyAddressDraft = () => ({ customer_name: '', phone: '', address_line1: '', address_line2: '', landmark: '', city: '', state: '', pincode: '' })

export function isCurrentDrawerRequest(request: DrawerIdentity, currentOrderId: string | null, currentGeneration: number): boolean {
  return request.orderId === currentOrderId && request.generation === currentGeneration
}

export function isCurrentDrawerQuote(quote: DrawerQuoteIdentity | null, current: DrawerQuoteIdentity | null): boolean {
  return quote !== null && current !== null && quote.orderId === current.orderId && quote.generation === current.generation && quote.contextKey === current.contextKey
}

export function canUseDraft(draft: DrawerIdentity | null, currentOrderId: string | null, currentGeneration: number, initializing: boolean): boolean {
  return !initializing && draft !== null && isCurrentDrawerRequest(draft, currentOrderId, currentGeneration)
}
