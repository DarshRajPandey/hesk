import { useMemo, useState } from 'react'
import { CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'
import { EventStream } from '../components/EventStream'
import type { MetricSample, SimEvent } from '../sim/types'
import { lab, summarise, useUi, useWorld, type RunRecord, type RunSummary } from '../state/lab'
import { Btn, Caveat, cx, Empty, Panel, pct, Stat } from '../ui/kit'

type MetricId = 'utilityRatio' | 'connectivity' | 'activeNodes' | 'components' | 'messages' | 'busyRatio' | 'meanEnergy' | 'agreement' | 'duplicated'
interface MetricDef { id: MetricId; label: string; unit: string; ratio: boolean; note: string }
const METRICS: MetricDef[] = [
  { id: 'utilityRatio', label: 'Mission utility', unit: '%', ratio: true, note: 'Σ priority × tier quality over tasks that are physically running, relative to every task at tier 0. A task executed by two partitions counts once.' },
  { id: 'connectivity', label: 'Network connectivity', unit: '%', ratio: true, note: 'Share of live node pairs that can reach each other over one or more radio links.' },
  { id: 'activeNodes', label: 'Active nodes', unit: 'nodes', ratio: false, note: 'Nodes that are powered and not failed.' },
  { id: 'components', label: 'Partitions', unit: '', ratio: false, note: 'Connected components of the radio graph.' },
  { id: 'messages', label: 'Communication overhead', unit: 'msg/tick', ratio: false, note: 'Modelled message count: two beacons per link, auction announce/bid/award, plan broadcasts and reconciliation events. HESK defines no wire protocol, so this is an estimate of shape, not of bytes.' },
  { id: 'busyRatio', label: 'Resource utilization', unit: '%', ratio: true, note: 'Share of live nodes holding a task role.' },
  { id: 'meanEnergy', label: 'Mean energy', unit: '%', ratio: true, note: 'Average remaining energy of live nodes (linear drain model).' },
  { id: 'agreement', label: 'Ownership agreement', unit: '%', ratio: true, note: 'Share of tasks for which every replica holds the same owner and tier.' },
  { id: 'duplicated', label: 'Duplicated tasks', unit: 'tasks', ratio: false, note: 'Tasks being executed by more than one partition at once (split-brain dual ownership).' },
]

interface Source { id: string; label: string; samples: MetricSample[]; events: SimEvent[]; summary: RunSummary; tickSeconds: number }
const fromRun = (r: RunRecord): Source => ({ id: r.id, label: r.label, samples: r.samples, events: r.events, summary: r.summary, tickSeconds: 5 })
const fmt = (m: MetricDef, v: number | undefined): string => (v === undefined ? '—' : m.ratio ? pct(v, v === 1 || v === 0 ? 0 : 1) : String(Math.round(v * 100) / 100))

function ChartTooltip({ active, payload, label, metric, names }: { active?: boolean; payload?: Array<{ dataKey: string; value: number; color: string }>; label?: number; metric: MetricDef; names: Record<string, string> }) {
  if (!active || !payload?.length) return null
  return (
    <div className="rounded-[2px] border border-line-2 bg-bg-2 px-2.5 py-1.5 shadow-lg">
      <div className="num text-[10px] text-ink-3">T+{label}s</div>
      {payload.map((p) => (
        <div key={p.dataKey} className="mt-0.5 flex items-center gap-2">
          <span className="h-0.5 w-3" style={{ background: p.color }} />
          <span className="num text-[12px] font-medium text-ink">{fmt(metric, p.value)}</span>
          <span className="text-[11px] text-ink-2">{names[p.dataKey]}</span>
        </div>
      ))}
    </div>
  )
}

const LANES: Array<{ id: SimEvent['source']; label: string; color: string }> = [
  { id: 'operator', label: 'Fault', color: 'var(--color-violet)' },
  { id: 'kernel', label: 'Kernel', color: 'var(--color-accent)' },
  { id: 'harness', label: 'Detect', color: 'var(--color-ink-3)' },
]
const Y_AXIS = 46
const RIGHT = 18

export function Observatory() {
  const world = useWorld()
  const ui = useUi()
  const [metricId, setMetricId] = useState<MetricId>('utilityRatio')
  const [primaryId, setPrimaryId] = useState('live')
  const [compareId, setCompareId] = useState('none')
  const [cursor, setCursor] = useState<number | null>(null)
  const [table, setTable] = useState(false)
  const [label, setLabel] = useState('')

  const live: Source = useMemo(() => ({ id: 'live', label: 'Live run', samples: world.metrics, events: world.events, summary: summarise(world), tickSeconds: world.tickSeconds }), [world])
  const sources = useMemo(() => [live, ...ui.runs.map(fromRun)], [live, ui.runs])
  const primary = sources.find((s) => s.id === primaryId) ?? live
  const compare = compareId === 'none' ? null : sources.find((s) => s.id === compareId && s.id !== primary.id) ?? null
  const metric = METRICS.find((m) => m.id === metricId) as MetricDef
  const ts = primary.tickSeconds

  const maxTick = Math.max(1, primary.samples.at(-1)?.tick ?? 0, compare?.samples.at(-1)?.tick ?? 0)
  const data = useMemo(() => {
    const a = new Map(primary.samples.map((s) => [s.tick, s[metricId]]))
    const b = new Map((compare?.samples ?? []).map((s) => [s.tick, s[metricId]]))
    return Array.from({ length: maxTick + 1 }, (_, t) => ({ t: t * ts, a: a.get(t), b: b.get(t) }))
  }, [primary, compare, metricId, maxTick, ts])

  const groups = useMemo(() => {
    const m = new Map<string, { lane: SimEvent['source']; tick: number; events: SimEvent[] }>()
    for (const e of primary.events) {
      if (e.tick === 0 && e.source !== 'operator') continue
      const k = `${e.source}:${e.tick}`
      const g = m.get(k) ?? { lane: e.source, tick: e.tick, events: [] }
      g.events.push(e)
      m.set(k, g)
    }
    return [...m.values()]
  }, [primary.events])
  const atCursor = cursor === null ? [] : primary.events.filter((e) => e.tick === cursor)
  const s = primary.summary
  const names = { a: primary.label, b: compare?.label ?? '' }

  return (
    <div className="flex flex-col gap-3 p-3">
      <div className="panel grid grid-cols-2 md:grid-cols-4 xl:grid-cols-7">
        <Stat label="Convergence time" value={s.meanConvergenceS === null ? '—' : s.meanConvergenceS.toFixed(0)} unit={s.meanConvergenceS === null ? '' : 's'} sub={s.meanConvergenceS === null ? 'no partition healed yet' : `link restored → ledgers merged · ${s.conflicts} conflicts`} />
        <Stat label="Recovery latency" value={s.meanResponseS === null ? '—' : s.meanResponseS.toFixed(1)} unit={s.meanResponseS === null ? '' : 's'} sub="fault → swarm response (mean)" />
        <Stat label="Lowest utility" value={pct(s.minUtility)} sub={`final ${pct(s.finalUtility)}`} tone={s.minUtility < 0.999 ? 'warn' : 'ok'} />
        <Stat label="Peak partitions" value={s.peakPartitions} sub={s.diverged ? `${s.diverged} keys differed after merge` : 'no post-merge divergence'} tone={s.diverged ? 'warn' : undefined} />
        <Stat label="Comm. overhead" value={s.messages.toLocaleString()} unit="msgs" sub={`${(s.messages / Math.max(1, s.ticks)).toFixed(0)} per tick · modelled`} />
        <Stat label="Run length" value={s.ticks * ts} unit="s" sub={`${s.ticks} ticks`} />
        <Stat label="Mission completion" value="n/a" sub="tasks are continuous services; see utility" />
      </div>

      <div className="flex flex-wrap items-center gap-x-4 gap-y-2 px-1">
        <label className="flex items-center gap-1.5"><span className="label">Run</span>
          <select className="field" value={primary.id} onChange={(e) => { setPrimaryId(e.target.value); setCursor(null) }}>
            {sources.map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </label>
        <label className="flex items-center gap-1.5"><span className="label">Compare with</span>
          <select className="field" value={compare?.id ?? 'none'} onChange={(e) => setCompareId(e.target.value)}>
            <option value="none">— none —</option>
            {sources.filter((r) => r.id !== primary.id).map((r) => <option key={r.id} value={r.id}>{r.label}</option>)}
          </select>
        </label>
        <div role="group" aria-label="Metric" className="flex flex-wrap gap-1">
          {METRICS.map((m) => (
            <button key={m.id} type="button" aria-pressed={m.id === metricId} onClick={() => setMetricId(m.id)}
              className={cx('h-6 rounded-[2px] border px-2 text-[11.5px]', m.id === metricId ? 'border-accent/70 bg-accent/15 text-accent' : 'border-line-2 bg-bg-2 text-ink-2 hover:text-ink')}>
              {m.label}
            </button>
          ))}
        </div>
      </div>

      <div className="grid gap-3 xl:grid-cols-[minmax(0,1fr)_340px]">
        <Panel
          title={metric.label} meta={metric.unit} bodyClass="p-0"
          actions={<Btn size="sm" tone="ghost" active={table} onClick={() => setTable((t) => !t)}>{table ? 'Chart' : 'Table'}</Btn>}
        >
          <p className="px-3 pt-2 text-[11px] leading-snug text-ink-3">{metric.note}</p>
          {compare && (
            <div className="flex gap-4 px-3 pt-2">
              <span className="flex items-center gap-1.5 text-[11.5px] text-ink-2"><span className="h-0.5 w-4 bg-s1" />{primary.label}</span>
              <span className="flex items-center gap-1.5 text-[11.5px] text-ink-2"><span className="h-0.5 w-4 bg-s2" />{compare.label}</span>
            </div>
          )}
          {table ? (
            <div className="m-3 max-h-[380px] overflow-auto rounded-[2px] border border-line">
              <table className="w-full border-collapse text-left">
                <thead className="sticky top-0 bg-bg-2"><tr className="label"><th className="px-3 py-1.5 font-normal">Time</th><th className="px-3 font-normal">{primary.label}</th>{compare && <th className="px-3 font-normal">{compare.label}</th>}</tr></thead>
                <tbody>
                  {data.map((d) => (
                    <tr key={d.t} className="border-t border-line/60"><td className="num px-3 py-0.5 text-[11px] text-ink-3">T+{d.t}s</td><td className="num px-3 text-[11px]">{fmt(metric, d.a)}</td>{compare && <td className="num px-3 text-[11px]">{fmt(metric, d.b)}</td>}</tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <>
              <div className="h-[300px] pt-2">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={data} margin={{ top: 8, right: RIGHT, bottom: 0, left: 0 }} onClick={(e) => { if (e && typeof e.activeLabel === 'number') setCursor(Math.round(e.activeLabel / ts)) }}>
                    <CartesianGrid stroke="var(--color-line)" vertical={false} />
                    <XAxis dataKey="t" type="number" domain={[0, maxTick * ts]} tickCount={9} stroke="var(--color-line-2)" tick={{ fill: 'var(--color-ink-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }} tickFormatter={(v: number) => `${v}s`} />
                    <YAxis width={Y_AXIS} domain={metric.ratio ? [0, 1] : [0, 'auto']} allowDecimals={false} stroke="var(--color-line-2)" tickLine={false}
                      tick={{ fill: 'var(--color-ink-3)', fontSize: 10, fontFamily: 'var(--font-mono)' }} tickFormatter={(v: number) => (metric.ratio ? `${Math.round(v * 100)}%` : String(v))} />
                    <Tooltip content={<ChartTooltip metric={metric} names={names} />} cursor={{ stroke: 'var(--color-ink-3)', strokeWidth: 1 }} isAnimationActive={false} />
                    {cursor !== null && <ReferenceLine x={cursor * ts} stroke="var(--color-accent)" strokeWidth={1} />}
                    <Line dataKey="a" type="stepAfter" stroke="var(--color-s1)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: 'var(--color-bg-1)', strokeWidth: 2 }} isAnimationActive={false} connectNulls />
                    {compare && <Line dataKey="b" type="stepAfter" stroke="var(--color-s2)" strokeWidth={2} dot={false} activeDot={{ r: 4, stroke: 'var(--color-bg-1)', strokeWidth: 2 }} isAnimationActive={false} connectNulls />}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <div className="border-t border-line pt-1 pb-2" aria-label="Event timeline">
                {LANES.map((lane) => (
                  <div key={lane.id} className="relative h-6">
                    <span className="label absolute top-1.5 left-2 w-[44px] !text-[8.5px]" title={lane.label}>{lane.label}</span>
                    <div className="absolute inset-y-0" style={{ left: Y_AXIS, right: RIGHT }}>
                      <div className="absolute top-1/2 h-px w-full bg-line" />
                      {groups.filter((g) => g.lane === lane.id).map((g) => (
                        <button key={g.tick} type="button" onClick={() => setCursor(g.tick === cursor ? null : g.tick)}
                          aria-label={`${g.events.length} ${lane.label.toLowerCase()} event(s) at T+${g.tick * ts}s`} aria-pressed={g.tick === cursor}
                          title={g.events.map((e) => e.title).join('\n')}
                          className="absolute top-0 flex h-6 w-6 -translate-x-1/2 items-center justify-center" style={{ left: `${(g.tick / maxTick) * 100}%` }}>
                          <span className="block h-2 w-2 rounded-full transition-transform hover:scale-150" style={{ background: lane.color, outline: g.tick === cursor ? '1px solid var(--color-ink)' : '2px solid var(--color-bg-1)', outlineOffset: g.tick === cursor ? 2 : 0 }} />
                        </button>
                      ))}
                    </div>
                  </div>
                ))}
              </div>
            </>
          )}
        </Panel>

        <Panel title={cursor === null ? 'Event timeline' : `Events at T+${cursor * ts}s`} meta={cursor === null ? 'select a marker or click the chart' : `${atCursor.length} event(s)`} bodyClass="" className="max-h-[470px]"
          actions={cursor !== null && <Btn size="sm" tone="ghost" onClick={() => setCursor(null)}>Clear</Btn>}>
          {cursor === null
            ? <EventStream events={primary.events.filter((e) => e.tick > 0 || e.source === 'operator')} tickSeconds={ts} compact onPick={(e) => setCursor(e.tick)} />
            : atCursor.length === 0 ? <Empty>No recorded event at this instant.</Empty> : <EventStream events={atCursor} tickSeconds={ts} />}
        </Panel>
      </div>

      <Panel title="Experimental runs" meta={`${ui.runs.length} saved · kept in this browser`} bodyClass=""
        actions={<>
          <input className="field !h-[22px] w-40 !text-[11px]" placeholder="Label for the live run" value={label} onChange={(e) => setLabel(e.target.value)} aria-label="Label for the live run" />
          <Btn size="sm" tone="primary" disabled={world.tick === 0} onClick={() => { lab.saveRun(label.trim() || `Run · ${world.preset} · seed ${world.seed} · ${world.tick} ticks`); setLabel('') }}>Save live run</Btn>
        </>}>
        <div className="overflow-x-auto">
          <table className="w-full min-w-[820px] border-collapse text-left">
            <thead><tr className="label border-b border-line">
              <th className="px-3 py-1.5 font-normal">Run</th><th className="px-2 font-normal">Scenario</th><th className="px-2 text-right font-normal">Length</th><th className="px-2 text-right font-normal">Lowest utility</th>
              <th className="px-2 text-right font-normal">Final utility</th><th className="px-2 text-right font-normal">Recovery latency</th><th className="px-2 text-right font-normal">Convergence</th>
              <th className="px-2 text-right font-normal">Conflicts</th><th className="px-2 text-right font-normal">Messages</th><th className="px-3 font-normal" />
            </tr></thead>
            <tbody>
              {sources.map((r) => {
                const rec = ui.runs.find((x) => x.id === r.id)
                return (
                  <tr key={r.id} className={cx('border-b border-line/60', r.id === primary.id && 'bg-s1/[0.07]', r.id === compare?.id && 'bg-s2/[0.08]')}>
                    <td className="px-3 py-1.5 text-[12px]">
                      <span className="mr-1.5 inline-block h-0.5 w-3 align-middle" style={{ background: r.id === primary.id ? 'var(--color-s1)' : r.id === compare?.id ? 'var(--color-s2)' : 'transparent' }} />{r.label}
                    </td>
                    <td className="num px-2 text-[11px] text-ink-2">{rec ? `${rec.preset} · seed ${rec.seed}` : `${world.preset} · seed ${world.seed}`}</td>
                    <td className="num px-2 text-right text-[11px]">{r.summary.ticks * 5}s</td>
                    <td className="num px-2 text-right text-[11px]">{pct(r.summary.minUtility, 1)}</td>
                    <td className="num px-2 text-right text-[11px]">{pct(r.summary.finalUtility, 1)}</td>
                    <td className="num px-2 text-right text-[11px]">{r.summary.meanResponseS === null ? '—' : `${r.summary.meanResponseS.toFixed(1)}s`}</td>
                    <td className="num px-2 text-right text-[11px]">{r.summary.meanConvergenceS === null ? '—' : `${r.summary.meanConvergenceS.toFixed(0)}s`}</td>
                    <td className="num px-2 text-right text-[11px]">{r.summary.conflicts}</td>
                    <td className="num px-2 text-right text-[11px]">{r.summary.messages.toLocaleString()}</td>
                    <td className="px-3 py-1 text-right whitespace-nowrap">
                      <Btn size="sm" tone="ghost" active={r.id === primary.id} onClick={() => { setPrimaryId(r.id); setCursor(null); if (compareId === r.id) setCompareId('none') }}>View</Btn>
                      <Btn size="sm" tone="ghost" active={r.id === compare?.id} disabled={r.id === primary.id} onClick={() => setCompareId(compareId === r.id ? 'none' : r.id)}>Compare</Btn>
                      {rec && <Btn size="sm" tone="ghost" onClick={() => { lab.deleteRun(r.id); if (primaryId === r.id) setPrimaryId('live'); if (compareId === r.id) setCompareId('none') }} aria-label={`Delete run ${r.label}`}>Delete</Btn>}
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
        {ui.runs.length === 0 && <p className="px-3 py-2 text-[11.5px] text-ink-3">Scripted experiments in Fault Injection save their run here automatically. Save the live run to compare free exploration.</p>}
      </Panel>

      <div className="grid gap-2 px-1 md:grid-cols-2">
        <Caveat>All figures describe the in-browser simulation. Times are simulated seconds ({world.tickSeconds}s per tick); recovery latency is dominated by the harness detection delay of {world.detectTicks} beacons.</Caveat>
        <Caveat tone="warn">Nothing here is a benchmark of HESK on real hardware. Decision latency, memory and radio behaviour on an edge device have not been measured by this project.</Caveat>
      </div>
    </div>
  )
}
