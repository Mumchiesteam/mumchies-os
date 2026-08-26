import { useMemo, useState } from 'react'
import type { QueueDateFilter, QueueDatePreset } from '../utils/queueDateFilter'

const isoDate = (date: Date) => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`
const parseLocalDate = (value: string) => value ? new Date(`${value}T00:00:00`) : null
const prettyDate = (value: string, includeYear = false) => {
  const date = parseLocalDate(value)
  return date ? new Intl.DateTimeFormat('en-US', { month: 'short', day: 'numeric', ...(includeYear ? { year: 'numeric' } : {}) }).format(date) : ''
}

export function presetDateRange(preset: QueueDatePreset, now = new Date()): QueueDateFilter {
  const today = new Date(now.getFullYear(), now.getMonth(), now.getDate())
  if (preset === 'all') return { preset, start: '', end: '' }
  if (preset === 'custom') return { preset, start: '', end: '' }
  const start = new Date(today), end = new Date(today)
  if (preset === 'yesterday') { start.setDate(start.getDate() - 1); end.setDate(end.getDate() - 1) }
  if (preset === 'last_7_days') start.setDate(start.getDate() - 6)
  if (preset === 'last_30_days') start.setDate(start.getDate() - 29)
  return { preset, start: isoDate(start), end: isoDate(end) }
}

export function dateRangeLabel(value: QueueDateFilter): string {
  if (value.preset === 'all' || !value.start || !value.end) return 'All Dates'
  if (value.start === value.end) return prettyDate(value.end, true)
  const sameYear = value.start.slice(0, 4) === value.end.slice(0, 4)
  return `${prettyDate(value.start, !sameYear)} – ${prettyDate(value.end, true)}`
}

export function QueueDateFilterControl({ value, onChange, label }: { value: QueueDateFilter; onChange: (value: QueueDateFilter) => void; label: string }) {
  const [open, setOpen] = useState(false)
  const [draft, setDraft] = useState(value)
  const [month, setMonth] = useState(() => parseLocalDate(value.end) || new Date())
  const days = useMemo(() => {
    const first = new Date(month.getFullYear(), month.getMonth(), 1)
    const start = new Date(first); start.setDate(start.getDate() - first.getDay())
    return Array.from({ length: 42 }, (_, index) => { const date = new Date(start); date.setDate(start.getDate() + index); return date })
  }, [month])
  const choosePreset = (preset: QueueDatePreset) => {
    const next = presetDateRange(preset)
    setDraft(next)
    if (next.end) setMonth(parseLocalDate(next.end) || new Date())
  }
  const chooseDay = (date: Date) => {
    const selected = isoDate(date)
    if (draft.preset !== 'custom' || !draft.start || (draft.start && draft.end)) setDraft({ preset: 'custom', start: selected, end: '' })
    else if (selected < draft.start) setDraft({ preset: 'custom', start: selected, end: draft.start })
    else setDraft({ preset: 'custom', start: draft.start, end: selected })
  }
  return <div className="relative">
    <button type="button" aria-label={label} aria-expanded={open} onClick={() => { setDraft(value); setOpen(current => !current) }} className="flex min-w-44 items-center gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2.5 text-left text-sm font-medium text-slate-600 outline-none hover:border-orange-300">
      <svg aria-hidden="true" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M16 3v4M8 3v4M3 10h18"/></svg>
      <span><span className="sr-only">{label}: </span>{dateRangeLabel(value)}</span>
    </button>
    {open && <div role="dialog" aria-label={`${label} range picker`} className="absolute left-0 top-full z-50 mt-2 w-[330px] rounded-xl border border-slate-200 bg-white p-3 shadow-xl">
      <div className="mb-3 flex flex-wrap gap-1">{([['all','All Dates'],['today','Today'],['yesterday','Yesterday'],['last_7_days','Last 7 Days'],['last_30_days','Last 30 Days'],['custom','Custom']] as const).map(([preset, text]) => <button type="button" key={preset} onClick={() => choosePreset(preset)} className={`rounded-full px-2.5 py-1 text-[11px] font-semibold ${draft.preset === preset ? 'bg-slate-900 text-white' : 'bg-slate-100 text-slate-600'}`}>{text}</button>)}</div>
      <div className="flex items-center justify-between"><button type="button" aria-label="Previous month" onClick={() => setMonth(current => new Date(current.getFullYear(), current.getMonth() - 1, 1))} className="rounded p-2 hover:bg-slate-100">‹</button><strong className="text-sm">{new Intl.DateTimeFormat('en-US', { month: 'long', year: 'numeric' }).format(month)}</strong><button type="button" aria-label="Next month" onClick={() => setMonth(current => new Date(current.getFullYear(), current.getMonth() + 1, 1))} className="rounded p-2 hover:bg-slate-100">›</button></div>
      <div className="mt-2 grid grid-cols-7 text-center text-[10px] font-bold text-slate-400">{['S','M','T','W','T','F','S'].map((day, index) => <span key={`${day}-${index}`}>{day}</span>)}</div>
      <div className="mt-1 grid grid-cols-7 gap-y-1">{days.map(date => { const key = isoDate(date), inMonth = date.getMonth() === month.getMonth(), inRange = Boolean(draft.start && draft.end && key >= draft.start && key <= draft.end), edge = key === draft.start || key === draft.end; return <button type="button" key={key} aria-label={key} onClick={() => chooseDay(date)} className={`h-9 text-xs ${!inMonth ? 'text-slate-300' : 'text-slate-700'} ${inRange ? 'bg-orange-100' : ''} ${edge ? 'rounded-full bg-orange-600 font-bold text-white' : 'hover:bg-orange-50'}`}>{date.getDate()}</button> })}</div>
      <p className="mt-2 min-h-5 text-xs font-medium text-slate-600">{draft.start ? `${prettyDate(draft.start, true)}${draft.end ? ` – ${prettyDate(draft.end, true)}` : ' – choose end date'}` : 'No date restriction'}</p>
      <div className="mt-2 flex justify-end gap-2"><button type="button" onClick={() => { const cleared = presetDateRange('all'); setDraft(cleared); onChange(cleared); setOpen(false) }} className="rounded-md px-3 py-2 text-xs font-semibold text-slate-600">Clear</button><button type="button" disabled={draft.preset !== 'all' && (!draft.start || !draft.end)} onClick={() => { onChange(draft); setOpen(false) }} className="rounded-md bg-slate-900 px-3 py-2 text-xs font-semibold text-white disabled:opacity-40">Apply</button></div>
    </div>}
  </div>
}
