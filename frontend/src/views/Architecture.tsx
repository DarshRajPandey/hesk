import { useState } from 'react'
import { COMPONENTS, EDGES, STATUS_META, type ArchComponent, type Status } from '../content/architecture'
import { Caveat, cx, Panel, Tag } from '../ui/kit'

const W = 208
const H = 62
const GX = 258
const GY = 104
const pos = (c: ArchComponent) => ({ x: 14 + (c.col / 3) * GX, y: 14 + c.row * GY })
const VIEW_W = 14 * 2 + 3 * GX + W
const VIEW_H = 14 * 2 + 4 * GY + H

function edgePath(a: ArchComponent, b: ArchComponent): string {
  const p = pos(a)
  const q = pos(b)
  if (a.row === b.row) {
    const right = q.x > p.x
    const dy = EDGES.some(([f, t]) => f === b.id && t === a.id) ? (right ? -9 : 9) : 0
    return `M${right ? p.x + W : p.x},${p.y + H / 2 + dy}L${right ? q.x - 5 : q.x + W + 5},${q.y + H / 2 + dy}`
  }
  const down = q.y > p.y
  const x1 = p.x + W / 2 + (q.x - p.x) * 0.12
  const x2 = q.x + W / 2 - (q.x - p.x) * 0.12
  const y1 = down ? p.y + H : p.y
  const y2 = down ? q.y - 5 : q.y + H + 5
  const mid = (y1 + y2) / 2
  return `M${x1},${y1}C${x1},${mid} ${x2},${mid} ${x2},${y2}`
}

export function Architecture() {
  const [selectedId, setSelectedId] = useState('degr')
  const [filter, setFilter] = useState<Status | 'all'>('all')
  const byId = new Map(COMPONENTS.map((c) => [c.id, c]))
  const selected = byId.get(selectedId) ?? (COMPONENTS[0] as ArchComponent)
  const counts = (s: Status) => COMPONENTS.filter((c) => c.status === s).length
  const meta = STATUS_META[selected.status]

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="panel flex flex-wrap items-center gap-x-5 gap-y-2 px-3 py-2">
        <span className="label">Implementation status</span>
        <button type="button" aria-pressed={filter === 'all'} onClick={() => setFilter('all')} className={cx('num text-[11px]', filter === 'all' ? 'text-accent' : 'text-ink-2 hover:text-ink')}>all {COMPONENTS.length}</button>
        {(Object.keys(STATUS_META) as Status[]).map((s) => (
          <button key={s} type="button" aria-pressed={filter === s} onClick={() => setFilter(filter === s ? 'all' : s)} title={STATUS_META[s].meaning}
            className={cx('flex items-center gap-1.5 text-[11.5px]', filter === s ? 'text-ink' : 'text-ink-2 hover:text-ink')}>
            <span className="h-2 w-2 rounded-[1px]" style={{ background: STATUS_META[s].color }} />{STATUS_META[s].label}<span className="num text-ink-3">{counts(s)}</span>
          </button>
        ))}
        <span className="ml-auto text-[11px] text-ink-3">Eight algorithms are implemented as a Python library with 29 passing unit tests. Nothing around them — transport, detection, runtime — exists yet.</span>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_400px]">
        <Panel title="System map" meta="select a component" bodyClass="p-2">
          <div className="overflow-x-auto">
            <svg viewBox={`0 0 ${VIEW_W} ${VIEW_H}`} className="w-full min-w-[760px]" role="group" aria-label="HESK architecture map">
              <defs>
                <marker id="arrow" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="var(--color-ink-3)" /></marker>
                <marker id="arrow-hot" viewBox="0 0 8 8" refX="7" refY="4" markerWidth="7" markerHeight="7" orient="auto"><path d="M0 0L8 4L0 8z" fill="var(--color-accent)" /></marker>
              </defs>
              {EDGES.map(([f, t]) => {
                const a = byId.get(f)
                const b = byId.get(t)
                if (!a || !b) return null
                const hot = f === selected.id || t === selected.id
                const ghost = a.status === 'unavailable' || a.status === 'planned'
                return <path key={`${f}-${t}`} d={edgePath(a, b)} fill="none" stroke={hot ? 'var(--color-accent)' : 'var(--color-ink-3)'} strokeOpacity={hot ? 0.9 : 0.5} strokeWidth={hot ? 1.4 : 1} strokeDasharray={ghost ? '3 4' : undefined} markerEnd={`url(#${hot ? 'arrow-hot' : 'arrow'})`} />
              })}
              {COMPONENTS.map((c) => {
                const p = pos(c)
                const sm = STATUS_META[c.status]
                const on = c.id === selected.id
                const dim = filter !== 'all' && c.status !== filter
                const ghost = c.status === 'unavailable' || c.status === 'planned'
                return (
                  <g key={c.id} transform={`translate(${p.x},${p.y})`} opacity={dim ? 0.25 : 1} role="button" tabIndex={0} aria-pressed={on}
                    aria-label={`${c.code !== '—' ? `Algorithm ${c.code}, ` : ''}${c.name}, ${sm.label}`} className="cursor-pointer"
                    onClick={() => setSelectedId(c.id)} onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); setSelectedId(c.id) } }}>
                    <rect width={W} height={H} rx={2} fill={on ? 'var(--color-bg-3)' : 'var(--color-bg-2)'} stroke={on ? 'var(--color-accent)' : 'var(--color-line-2)'} strokeDasharray={ghost && !on ? '4 3' : undefined} />
                    <rect width={3} height={H} fill={sm.color} />
                    <text x={14} y={20} className="num" fontSize="10" fill="var(--color-ink-3)">{c.code === '—' ? c.concept.toUpperCase() : `ALGORITHM ${c.code}`}</text>
                    <text x={14} y={38} fontSize="12.5" fontWeight={500} fill={ghost ? 'var(--color-ink-2)' : 'var(--color-ink)'}>{c.name.length > 29 ? `${c.name.slice(0, 28)}…` : c.name}</text>
                    <text x={14} y={53} className="num" fontSize="9.5" fill={sm.color}>{sm.label.toUpperCase()}</text>
                  </g>
                )
              })}
            </svg>
          </div>
        </Panel>

        <Panel title={selected.code === '—' ? selected.concept : `Algorithm ${selected.code}`} actions={<Tag color={meta.color} solid>{meta.label.toUpperCase()}</Tag>}>
          <div className="space-y-3">
            <div>
              <h3 className="text-[15px] font-semibold">{selected.name}</h3>
              <p className="mt-1 text-[12.5px] leading-snug text-ink-2">{selected.purpose}</p>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div><div className="label mb-1">Inputs</div><ul className="space-y-0.5 text-[11.5px] text-ink-2">{selected.inputs.length ? selected.inputs.map((i) => <li key={i}>{i}</li>) : <li className="text-ink-3">—</li>}</ul></div>
              <div><div className="label mb-1">Outputs</div><ul className="space-y-0.5 text-[11.5px] text-ink-2">{selected.outputs.length ? selected.outputs.map((i) => <li key={i}>{i}</li>) : <li className="text-ink-3">—</li>}</ul></div>
            </div>
            <div>
              <div className="label mb-1">Source</div>
              {selected.source.length ? <ul className="num space-y-0.5 text-[11px] text-ink-2">{selected.source.map((s) => <li key={s}>{s}</li>)}</ul> : <p className="text-[11.5px] text-ink-3">No code in the repository.</p>}
              <p className="num mt-1 text-[11px] text-ink-3">Tests: {selected.tests}</p>
            </div>
            <div><div className="label mb-1">In this laboratory</div><p className="text-[12px] leading-snug text-ink-2">{selected.lab}</p></div>
            <div>
              <div className="label mb-1.5">Known limits</div>
              <div className="space-y-1.5">{selected.gaps.map((g) => <Caveat key={g} tone={selected.status === 'implemented' ? 'warn' : 'info'}>{g}</Caveat>)}</div>
            </div>
          </div>
        </Panel>
      </div>

      <Panel title="Component index" bodyClass="">
        <div className="overflow-x-auto">
          <table className="w-full min-w-[640px] border-collapse text-left">
            <thead><tr className="label border-b border-line"><th className="px-3 py-1.5 font-normal">Component</th><th className="px-2 font-normal">Concept</th><th className="px-2 font-normal">Status</th><th className="px-3 font-normal">Tests</th></tr></thead>
            <tbody>
              {COMPONENTS.filter((c) => filter === 'all' || c.status === filter).map((c) => (
                <tr key={c.id} className={cx('cursor-pointer border-b border-line/60 hover:bg-bg-2', c.id === selected.id && 'bg-accent/[0.06]')} onClick={() => setSelectedId(c.id)}>
                  <td className="px-3 py-1.5 text-[12px]"><span className="num mr-2 text-[10.5px] text-ink-3">{c.code}</span>{c.name}</td>
                  <td className="px-2 text-[11.5px] text-ink-2">{c.concept}</td>
                  <td className="px-2"><span className="flex items-center gap-1.5 text-[11.5px]" style={{ color: STATUS_META[c.status].color }}><span className="h-1.5 w-1.5 rounded-[1px]" style={{ background: STATUS_META[c.status].color }} />{STATUS_META[c.status].label}</span></td>
                  <td className="num px-3 text-[11px] text-ink-3">{c.tests}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>
    </div>
  )
}
