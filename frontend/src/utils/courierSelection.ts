export type CanonicalCourierSelection = {
  provider?: string | null
  courier_id?: string | null
  courier_name?: string | null
  mode?: string | null
}

const normalized = (value: string | null | undefined) => String(value || '').trim().toLowerCase()

export function courierSelectionKey(selection: CanonicalCourierSelection | null | undefined): string | null {
  if (!selection?.courier_id || !selection.courier_name || !selection.provider) return null
  return [
    normalized(selection.provider),
    String(selection.courier_id).trim(),
    normalized(selection.courier_name),
    normalized(selection.mode),
  ].join('::')
}

export function courierSelectionMatches(
  persisted: CanonicalCourierSelection | null | undefined,
  current: CanonicalCourierSelection | null | undefined,
): boolean {
  const persistedKey = courierSelectionKey(persisted)
  return Boolean(persistedKey && persistedKey === courierSelectionKey(current))
}
