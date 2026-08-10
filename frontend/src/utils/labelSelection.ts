export type LabelSelectable = { order_id?: string | null; provider?: string | null }

export function selectAllLabelIds(
  all: LabelSelectable[], displayed: LabelSelectable[], selected: Set<string>, checked: boolean,
): Set<string> {
  const next = new Set(selected)
  const displayedIds = displayed.map(item => String(item.order_id || '')).filter(Boolean)
  if (!checked) {
    displayedIds.forEach(id => next.delete(id))
    return next
  }
  const selectedProvider = all.find(item => selected.has(String(item.order_id || '')))?.provider
  const provider = selectedProvider || displayed.find(item => item.order_id)?.provider
  displayed.filter(item => item.provider === provider).forEach(item => {
    if (item.order_id) next.add(String(item.order_id))
  })
  return next
}

export function selectAllLabelState(
  all: LabelSelectable[], displayed: LabelSelectable[], selected: Set<string>,
): { checked: boolean; indeterminate: boolean; eligible: number } {
  const selectedProvider = all.find(item => selected.has(String(item.order_id || '')))?.provider
  const provider = selectedProvider || displayed.find(item => item.order_id)?.provider
  const eligible = displayed.filter(item => item.provider === provider && item.order_id).map(item => String(item.order_id))
  const selectedCount = eligible.filter(id => selected.has(id)).length
  return { checked: eligible.length > 0 && selectedCount === eligible.length, indeterminate: selectedCount > 0 && selectedCount < eligible.length, eligible: eligible.length }
}
