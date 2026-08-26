import type { QueueDateFilter, QueueDatePreset } from '../utils/queueDateFilter'

export function QueueDateFilterControl({ value, onChange, label }: { value: QueueDateFilter; onChange: (value: QueueDateFilter) => void; label: string }) {
  const setPreset = (preset: QueueDatePreset) => onChange({ preset, start: preset === 'custom' ? value.start : '', end: preset === 'custom' ? value.end : '' })
  return <div className="flex flex-wrap items-center gap-1">
    <label className="flex items-center gap-1 text-xs text-slate-500"><span>{label}</span><select aria-label={label} value={value.preset} onChange={event => setPreset(event.target.value as QueueDatePreset)} className="rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-sm font-medium text-slate-600 outline-none focus:border-orange-300"><option value="all">All Dates</option><option value="today">Today</option><option value="yesterday">Yesterday</option><option value="last_7_days">Last 7 Days</option><option value="custom">Custom</option></select></label>
    {value.preset === 'custom' && <><input type="date" aria-label={`${label} from`} value={value.start} onChange={event => onChange({ ...value, start: event.target.value })} className="rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs text-slate-600" /><span className="text-xs text-slate-400">to</span><input type="date" aria-label={`${label} to`} value={value.end} onChange={event => onChange({ ...value, end: event.target.value })} className="rounded-lg border border-slate-200 bg-white px-2 py-2 text-xs text-slate-600" /></>}
  </div>
}
