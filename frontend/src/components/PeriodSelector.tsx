export type PeriodPreset = 'today' | 'yesterday' | 'last_7_days' | 'month_to_date' | 'last_30_days' | 'custom'

const options: [PeriodPreset, string][] = [['today', 'Today'], ['yesterday', 'Yesterday'], ['last_7_days', 'Last 7 Days'], ['month_to_date', 'Month to Date'], ['last_30_days', 'Last 30 Days'], ['custom', 'Custom']]

export function PeriodSelector({ preset, start, end, onChange, prefix }: { preset: PeriodPreset; start: string; end: string; prefix: string; onChange: (preset: PeriodPreset, start: string, end: string) => void }) {
  return <div className="flex flex-wrap items-center gap-1.5">{options.map(([key, label]) => <button key={key} onClick={() => onChange(key, start, end)} className={`rounded-md px-2.5 py-1.5 text-xs font-semibold ${preset === key ? 'bg-slate-900 text-white' : 'border border-slate-200 bg-white text-slate-600'}`}>{label}</button>)}{preset === 'custom' && <><input aria-label={`${prefix} from date`} type="date" value={start} onChange={event => onChange(preset, event.target.value, end)} className="rounded-md border px-2 py-1 text-xs"/><span className="text-xs text-slate-400">to</span><input aria-label={`${prefix} to date`} type="date" value={end} onChange={event => onChange(preset, start, event.target.value)} className="rounded-md border px-2 py-1 text-xs"/></>}</div>
}
