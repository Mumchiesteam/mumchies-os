import { displayEngageValue, engageCategory, engageFlowStyles, engageStyle, engageTooltip } from '../utils/engage'

export function EngageCircle({ label, stageName, value, message, enabled = true }: { label: string; stageName: string; value: unknown; message: string | null; enabled?: boolean }) {
  const unknown = engageCategory(value) === 'unknown'
  return <span title={engageTooltip(stageName, value, message)} aria-label={`${stageName}: ${message ?? ''}; raw value ${displayEngageValue(value)}${unknown ? '; unknown status' : ''}`} className={`relative inline-flex h-6 w-6 shrink-0 items-center justify-center rounded-full text-[8px] font-bold ${enabled ? engageStyle(value) : 'bg-slate-300 text-slate-700'}`}>{label}{unknown && <span aria-hidden="true" className="absolute -right-1 -top-1 text-[9px] font-black text-amber-700">!</span>}</span>
}

export function EngageProgress({ stages, lastSynced }: { stages: Array<{ abbreviation: string; name: string; value: unknown; message: string | null }>; lastSynced: string }) {
  const styles = engageFlowStyles(stages.map(stage => stage.value))
  return <div className="px-1 py-1">
    <div className="flex items-start">
      {stages.map((stage, index) => <div key={stage.name} className="contents">
        <div className="flex w-24 shrink-0 flex-col items-center text-center">
          <span title={stage.message || ''} aria-label={`${stage.name}: ${stage.message || ''}`} className={`inline-flex h-9 w-9 items-center justify-center rounded-full text-[10px] font-bold ${styles[index]}`}>{stage.abbreviation}</span>
          <span className="mt-1.5 text-[10px] font-medium leading-tight text-slate-500">{stage.name}</span>
        </div>
        {index < stages.length - 1 && <span aria-hidden="true" className="mt-[17px] min-w-6 flex-1 border-t-2 border-dotted border-slate-300" />}
      </div>)}
    </div>
    <p className="mt-3 text-[11px] text-slate-400">Last synced: {lastSynced}</p>
  </div>
}
