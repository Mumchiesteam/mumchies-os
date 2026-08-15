export type DrawerIdentity = { orderId: string; generation: number }

export const emptyAddressDraft = () => ({ customer_name: '', phone: '', address_line1: '', address_line2: '', landmark: '', city: '', state: '', pincode: '' })

export function isCurrentDrawerRequest(request: DrawerIdentity, currentOrderId: string | null, currentGeneration: number): boolean {
  return request.orderId === currentOrderId && request.generation === currentGeneration
}

export function canUseDraft(draft: DrawerIdentity | null, currentOrderId: string | null, currentGeneration: number, initializing: boolean): boolean {
  return !initializing && draft !== null && isCurrentDrawerRequest(draft, currentOrderId, currentGeneration)
}
