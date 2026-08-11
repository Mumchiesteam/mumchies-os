export type CanonicalCourierSelection = {
  provider?: string | null
  courier_id?: string | null
  courier_name?: string | null
  mode?: string | null
}

const normalized = (value: string | null | undefined) => String(value || '').trim().toLowerCase()

export function courierSelectionMatches(
  persisted: CanonicalCourierSelection | null | undefined,
  current: CanonicalCourierSelection | null | undefined,
): boolean {
  if (!persisted || !current) return false
  return String(persisted.courier_id || '') === String(current.courier_id || '')
    && normalized(persisted.provider) === normalized(current.provider)
    && normalized(persisted.courier_name) === normalized(current.courier_name)
    && normalized(persisted.mode) === normalized(current.mode)
}
