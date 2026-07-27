import { displayEngageValue, engageCategory, engageStyle, engageTooltip } from '../utils/engage'

export function EngageCircle({ label, stageName, value, message }: { label: string; stageName: string; value: unknown; message: string | null }) {
  const unknown = engageCategory(value) === 'unknown'
  return <span title={engageTooltip(stageName, value, message)} aria-label={`${stageName}: ${message ?? ''}; raw value ${displayEngageValue(value)}${unknown ? '; unknown status' : ''}`} className={`relative inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[8px] font-bold ${engageStyle(value)}`}>{label}{unknown && <span aria-hidden="true" className="absolute -right-1 -top-1 text-[9px] font-black text-amber-700">!</span>}</span>
}
