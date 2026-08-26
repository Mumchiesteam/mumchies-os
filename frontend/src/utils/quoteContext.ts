export type QuoteAddress = {
  customer_name: string; phone: string; address_line1: string; address_line2: string
  landmark: string; city: string; state: string; pincode: string
}
export type QuotePackage = { weight_kg: number; length_cm: number | null; breadth_cm: number | null; height_cm: number | null }

export function quoteAddressesMatch(left: QuoteAddress, right: Partial<Record<keyof QuoteAddress, string | null>> | null | undefined): boolean {
  if (!right) return false
  return (Object.keys(left) as (keyof QuoteAddress)[]).every(key => left[key].trim() === String(right[key] ?? '').trim())
}

export function quoteContextKey(input: {
  orderId: string; generation: number; address: QuoteAddress; paymentMode: string; codAmount: number; package: QuotePackage
}): string {
  const clean = (value: string) => value.trim()
  return JSON.stringify({
    order_id: input.orderId, generation: input.generation,
    destination: Object.fromEntries(Object.entries(input.address).map(([key, value]) => [key, clean(value)])),
    payment_mode: input.paymentMode === 'Prepaid' ? 'Prepaid' : 'COD',
    cod_amount: input.paymentMode === 'Prepaid' ? 0 : Number(input.codAmount),
    package: input.package,
  })
}

export function quoteSelectionGate(input: { eligible: boolean; contextMatches: boolean; addressVerified: boolean; paymentMode: string; codConfirmed: boolean }): { enabled: boolean; reason: string | null } {
  if (!input.contextMatches) return { enabled: false, reason: 'Refreshing courier options…' }
  if (!input.addressVerified) return { enabled: false, reason: 'Verify address to select' }
  if (input.paymentMode !== 'Prepaid' && !input.codConfirmed) return { enabled: false, reason: 'COD confirmation required' }
  if (!input.eligible) return { enabled: false, reason: 'Complete booking requirements to select' }
  return { enabled: true, reason: null }
}
