export const engageCategory = (value: unknown) => ({
  '0': 'pending', '1': 'pending', '2': 'successful', '21': 'successful',
  '3': 'cancelled', '6': 'disabled', NA: 'disabled',
} as const)[String(value)] || 'unknown'

export const engageStyle = (value: unknown) => engageCategory(value) === 'successful'
  ? 'bg-emerald-500 text-white'
  : engageCategory(value) === 'cancelled'
    ? 'bg-rose-500 text-white'
  : engageCategory(value) === 'pending'
    ? 'bg-amber-400 text-slate-900'
    : 'bg-slate-300 text-slate-700'

export const engageFlowStyles = (values: unknown[]) => values.map((value, index) => {
  const priorStagesComplete = values.slice(0, index).every(prior => engageCategory(prior) === 'successful')
  return priorStagesComplete ? engageStyle(value) : 'bg-slate-300 text-slate-700'
})

export const displayEngageValue = (value: unknown) => {
  if (value == null) return '—'
  if (typeof value === 'object') {
    try { return JSON.stringify(value) } catch { return String(value) }
  }
  return String(value)
}

export const engageTooltip = (stageName: string, value: unknown, message: string | null) => `${stageName}\n${message ?? ''}\nRaw value: ${displayEngageValue(value)}${engageCategory(value) === 'unknown' ? '\nWarning: Unknown Engage value' : ''}`
