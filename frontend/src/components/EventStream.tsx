import { useState } from 'react'
import type { SimEvent, Source } from '../sim/types'
import { cx, Empty, SEVERITY_COLOR, SourceTag, Tag } from '../ui/kit'

type Filter = 'all' | Source

/** Newest-first event log. Every row carries its provenance: kernel decision, harness bookkeeping or operator action. */
export function EventStream({ events, tickSeconds, onSelectNode, limit = 120, compact, activeId, onPick }: {
  events: SimEvent[]; tickSeconds: number; onSelectNode?: (id: string) => void; limit?: number; compact?: boolean
  activeId?: number | null; onPick?: (e: SimEvent) => void
}) {
  const [filter, setFilter] = useState<Filter>('all')
  const shown = events.filter((e) => filter === 'all' || e.source === filter).slice(-limit).reverse()
  return (
    <div className="flex h-full min-h-0 flex-col">
      {!compact && (
        <div className="flex shrink-0 items-center gap-1 border-b border-line px-3 py-1.5">
          {(['all', 'kernel', 'operator', 'harness'] as Filter[]).map((f) => (
            <button key={f} type="button" aria-pressed={filter === f} onClick={() => setFilter(f)}
              className={cx('num h-5 rounded-[2px] px-1.5 text-[10px] tracking-wide uppercase', filter === f ? 'bg-accent/15 text-accent' : 'text-ink-3 hover:text-ink')}>
              {f}
            </button>
          ))}
          <span className="num ml-auto text-[10px] text-ink-3">{shown.length} shown</span>
        </div>
      )}
      <ol className="min-h-0 flex-1 overflow-auto" aria-live="polite">
        {shown.length === 0 && <Empty>No events yet.</Empty>}
        {shown.map((e) => (
          <li key={e.id}
            onClick={onPick ? () => onPick(e) : undefined}
            className={cx('grid grid-cols-[52px_1fr] gap-x-2 border-b border-line/60 px-3 py-1.5', onPick && 'cursor-pointer hover:bg-bg-2', activeId === e.id && 'bg-bg-2')}>
            <span className="num pt-px text-[10.5px] text-ink-3">T+{String(e.tick * tickSeconds).padStart(3, '0')}s</span>
            <div className="min-w-0">
              <div className="flex items-start gap-1.5">
                <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLOR[e.severity] }} />
                <span className="min-w-0 flex-1 text-[12px] leading-snug text-ink">{e.title}</span>
                {e.algo && <Tag title={`HESK algorithm ${e.algo}`}>{e.algo}</Tag>}
                <SourceTag source={e.source} />
              </div>
              {e.detail && !compact && <div className="mt-0.5 pl-3 text-[11px] leading-snug text-ink-3">{e.detail}</div>}
              {onSelectNode && e.nodeIds.length > 0 && e.nodeIds.length <= 4 && !compact && (
                <div className="mt-0.5 flex gap-2 pl-3">
                  {e.nodeIds.map((id) => (
                    <button key={id} type="button" className="num text-[10.5px] text-ink-2 hover:text-accent hover:underline" onClick={(ev) => { ev.stopPropagation(); onSelectNode(id) }}>{id}</button>
                  ))}
                </div>
              )}
            </div>
          </li>
        ))}
      </ol>
    </div>
  )
}
