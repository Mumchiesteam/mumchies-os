import type { NDRKpi, NDRSourceHealth, NDRSummary } from '../services/ndr'

export const toggleKpi = (current:NDRKpi|undefined, next:NDRKpi):NDRKpi|undefined => current===next ? undefined : next

export const kpiButtonClass = (active:boolean) => `cursor-pointer rounded-lg border px-3 py-2 text-left shadow-sm transition ${active?'border-orange-400 bg-orange-50 ring-1 ring-orange-300':'border-slate-200 bg-white hover:border-slate-300'}`

export const shopifyPresentation = (summary:NDRSummary) => {
  const health=summary.source_health||{}, counts=summary.source_counts||{}, raw=health.shopify
  const shopify: NDRSourceHealth=raw&&!Array.isArray(raw)?raw:{}
  const warnings=Array.isArray(health.warnings)?health.warnings.filter(value=>typeof value==='string'&&value.trim()):[]
  const matched=shopify.phones_matched??counts.phones_matched, total=shopify.phones_total??counts.phones_total
  const matchText=typeof matched==='number'&&typeof total==='number'?`${matched}/${total} matched`:(shopify.error||'Unavailable')
  const sourceLabel=shopify.source==='api'?'API':shopify.source==='gdrive_csv'?'GDrive fallback':shopify.source==='none'?'Unavailable':''
  const visibleWarnings=shopify.source==='gdrive_csv'?warnings.filter(warning=>warning.toLowerCase().includes('gdrive')):warnings.filter(warning=>!warning.toLowerCase().includes('gdrive'))
  return {shopify,matchText,sourceLabel,visibleWarnings}
}
