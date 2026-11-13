import { useMemo, useState } from 'react'
import { computeScarcity, dynamicTheta } from '../kernel/allocation'
import { computeFullMatch } from '../kernel/matching'
import type { CapabilityState } from '../kernel/types'
import { ARCHETYPES, DIMENSIONS, taskById, WORLD_METRES } from '../sim/catalog'
import type { NodeView, WorldSnapshot } from '../sim/types'
import { lab } from '../state/lab'
import { Btn, cx, Icon, Meter, SEVERITY_COLOR, Tag } from '../ui/kit'
import { Glyph } from './glyphs'

const HEALTH = { NOMINAL: 'var(--color-ok)', DEGRADED: 'var(--color-warn)', DEPLETED: 'var(--color-warn)', FAILED: 'var(--color-crit)' } as const
const norm = (dim: string, v: unknown): number =>
  typeof v === 'number' ? Math.min(1, v / (DIMENSIONS[dim]?.max ?? 1)) : v === true ? 1 : 0
const RADAR_DIMS = Object.keys(DIMENSIONS).filter((d) => DIMENSIONS[d]?.type !== 'CATEGORICAL')

function Radar({ node }: { node: NodeView }) {
  const R = 46
  const pt = (i: number, v: number): string => {
    const a = (-90 + (360 / RADAR_DIMS.length) * i) * (Math.PI / 180)
    return `${(R * v * Math.cos(a)).toFixed(1)},${(R * v * Math.sin(a)).toFixed(1)}`
  }
  const shape = (dims: NodeView['dims']) => RADAR_DIMS.map((d, i) => pt(i, norm(d, dims[d]))).join(' ')
  return (
    <svg viewBox="-74 -62 148 124" className="w-full max-w-[220px]" role="img" aria-label="Capability vector radar; values are listed in the table below">
      {[0.33, 0.66, 1].map((r) => <polygon key={r} points={RADAR_DIMS.map((_, i) => pt(i, r)).join(' ')} fill="none" stroke="var(--color-line-2)" strokeWidth={0.7} />)}
      {RADAR_DIMS.map((d, i) => {
        const [x, y] = pt(i, 1.24).split(',').map(Number) as [number, number]
        return (
          <g key={d}>
            <line x2={pt(i, 1).split(',')[0]} y2={pt(i, 1).split(',')[1]} stroke="var(--color-line-2)" strokeWidth={0.7} />
            <text x={x} y={y + 3} textAnchor="middle" className="num" fontSize="7.5" fill="var(--color-ink-3)">{d}</text>
          </g>
        )
      })}
      <polygon points={shape(node.baseDims)} fill="none" stroke="var(--color-ink-3)" strokeWidth={0.8} strokeDasharray="2 2" />
      <polygon points={shape(node.dims)} fill="var(--color-accent)" fillOpacity={0.16} stroke="var(--color-accent)" strokeWidth={1.3} strokeLinejoin="round" />
    </svg>
  )
}

function Row({ k, children }: { k: string; children: React.ReactNode }) {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-line/60 py-1">
      <span className="label shrink-0">{k}</span>
      <span className="num min-w-0 text-right text-[11.5px] text-ink">{children}</span>
    </div>
  )
}

export function NodeInspector({ world, nodeId, onClose }: { world: WorldSnapshot; nodeId: string; onClose: () => void }) {
  const node = world.nodes.find((n) => n.id === nodeId)
  const [dim, setDim] = useState('camera')
  const peers: CapabilityState[] = useMemo(() => {
    const r = world.replicas.find((x) => x.id === node?.replicaId)
    return (r?.members ?? []).map((id) => world.nodes.find((n) => n.id === id)).filter((n): n is NodeView => !!n)
      .map((n) => ({ nodeId: n.id, timestamp: 0, dimensions: n.dims }))
  }, [world, node?.replicaId])
  if (!node) return null

  const arch = ARCHETYPES[node.archetype]
  const replica = world.replicas.find((r) => r.id === node.replicaId)
  const task = replica?.tasks.find((t) => t.taskId === node.role?.taskId)
  const links = world.links.filter((l) => l.a === node.id || l.b === node.id)
  const events = world.events.filter((e) => e.nodeIds.includes(node.id)).slice(-6).reverse()
  const state: CapabilityState = { nodeId: node.id, timestamp: 0, dimensions: node.dims }
  const dims = Object.keys(DIMENSIONS).filter((d) => d in node.baseDims)
  const degradable = dims.filter((d) => DIMENSIONS[d]?.type !== 'CATEGORICAL')
  const chosen = degradable.includes(dim) ? dim : degradable[0] ?? ''
  const altered = dims.some((d) => node.dims[d] !== node.baseDims[d])

  return (
    <div className="flex h-full min-h-0 flex-col">
      <header className="flex shrink-0 items-start gap-2.5 border-b border-line px-3 py-2.5">
        <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-[2px] border border-line-2 bg-bg-2"><Glyph archetype={node.archetype} size={20} color="var(--color-accent)" /></div>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <h3 className="num text-[15px] leading-none font-medium">{node.id}</h3>
            <Tag color={HEALTH[node.health]} solid>{node.health}</Tag>
            {node.isolated && <Tag color="var(--color-crit)">RADIO JAMMED</Tag>}
          </div>
          <div className="mt-1 text-[12px] text-ink-2">{arch.label}</div>
          <div className="text-[11px] text-ink-3">{arch.hardware}</div>
        </div>
        <button type="button" aria-label="Close inspector" onClick={onClose} className="rounded-[2px] p-1 text-ink-3 hover:bg-bg-3 hover:text-ink"><Icon name="close" /></button>
      </header>

      <div className="min-h-0 flex-1 space-y-4 overflow-auto px-3 py-3">
        <section>
          <Row k="Role">{task && node.role ? <>{task.name} · T{node.role.tier}{node.role.kind === 'COALITION' ? ' · coalition' : ''}</> : node.alive ? 'idle — available' : '—'}</Row>
          {node.role && node.role.kind === 'COALITION' && <Row k="Provides">{node.role.provides.join(', ') || 'capacity share'}</Row>}
          <Row k="Replica">{node.replicaId ?? '—'}{replica ? ` · ${replica.members.length} nodes` : ''}</Row>
          <Row k="Position">E {Math.round(node.x * WORLD_METRES)} · N {Math.round((1 - node.y) * WORLD_METRES)} m</Row>
          <Row k="Links">{node.neighbours.length} up{links.some((l) => !l.up) ? ` · ${links.filter((l) => !l.up).length} jammed` : ''}</Row>
          <Row k="Joined">T+{node.joinedTick * world.tickSeconds}s</Row>
          <div className="py-1.5">
            <div className="mb-1 flex justify-between"><span className="label">Energy</span><span className="num text-[11.5px]">{Math.round(node.energy * 100)}%</span></div>
            <Meter value={node.energy} color={node.energy < 0.25 ? 'var(--color-warn)' : 'var(--color-ok)'} />
          </div>
        </section>

        <section>
          <h4 className="label mb-1.5 !text-ink-2">Capability vector</h4>
          <div className="flex justify-center"><Radar node={node} /></div>
          <table className="mt-1 w-full border-collapse">
            <thead>
              <tr className="label text-left"><th className="py-1 font-normal">Dimension</th><th className="font-normal">Value</th><th className="w-[72px] font-normal" /><th className="text-right font-normal" title="Scarcity σ inside this node's replica: share of peers lacking a meaningful amount (Algorithm 004)">σ</th></tr>
            </thead>
            <tbody>
              {dims.map((d) => {
                const v = node.dims[d]
                const base = node.baseDims[d]
                const meta = DIMENSIONS[d]
                const sigma = meta?.type === 'CATEGORICAL' || peers.length === 0 ? null : computeScarcity(d, peers, dynamicTheta(d, peers))
                return (
                  <tr key={d} className="border-t border-line/60">
                    <td className="py-1 text-[11.5px] text-ink-2">{meta?.label ?? d}<span className="num ml-1 text-[9px] text-ink-3">{meta?.type.slice(0, 4)}</span></td>
                    <td className={cx('num text-[11.5px]', v !== base && 'text-warn')}>{typeof v === 'number' ? v.toFixed(2) : String(v)}</td>
                    <td>{meta?.type !== 'CATEGORICAL' && <Meter value={norm(d, v)} mark={v !== base ? norm(d, base) : undefined} color={v !== base ? 'var(--color-warn)' : 'var(--color-accent)'} />}</td>
                    <td className="num text-right text-[11px]" style={{ color: sigma !== null && sigma >= 0.75 ? 'var(--color-violet)' : 'var(--color-ink-3)' }}>{sigma === null ? '—' : sigma.toFixed(2)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>

        <section>
          <h4 className="label mb-1.5 !text-ink-2" title="Algorithm 003: required dimensions decide eligibility; preferred dimensions set quality">Solo eligibility · Algorithm 003</h4>
          <div className="space-y-1">
            {world.taskIds.map((id) => {
              const def = taskById(id)
              return (
                <div key={id} className="flex items-center gap-2">
                  <span className="num w-8 text-[11px] text-ink-2">{def.code}</span>
                  <div className="flex flex-1 gap-1">
                    {def.tiers.map((tier) => {
                      const m = computeFullMatch(state, tier.required, tier.preferred)
                      return (
                        <span key={tier.tierLevel}
                          title={m.eligible ? `Tier ${tier.tierLevel} (${tier.label}): eligible, match quality ${m.quality.toFixed(2)}` : `Tier ${tier.tierLevel} (${tier.label}): unmet ${m.unmetRequired.join(', ')}`}
                          className={cx('num flex h-[18px] flex-1 items-center justify-center rounded-[2px] border text-[9.5px]', m.eligible ? 'border-ok/50 bg-ok/10 text-ok' : 'border-line-2 text-ink-3')}>
                          T{tier.tierLevel}{m.eligible ? ` ${m.quality.toFixed(2)}` : ''}
                        </span>
                      )
                    })}
                  </div>
                </div>
              )
            })}
          </div>
        </section>

        <section>
          <h4 className="label mb-1.5 !text-ink-2">Neighbours · {links.length}</h4>
          {links.length === 0 ? <p className="text-[11.5px] text-ink-3">No node within radio range.</p> : (
            <table className="w-full border-collapse">
              <thead><tr className="label text-left"><th className="py-1 font-normal">Node</th><th className="text-right font-normal">Range</th><th className="text-right font-normal">Latency</th><th className="text-right font-normal">Bandwidth</th></tr></thead>
              <tbody>
                {links.map((l) => {
                  const other = l.a === node.id ? l.b : l.a
                  return (
                    <tr key={other} className="border-t border-line/60">
                      <td className="py-1"><button type="button" className={cx('num text-[11.5px] hover:underline', l.up ? 'text-ink hover:text-accent' : 'text-crit')} onClick={() => lab.select(other)}>{other}</button></td>
                      <td className="num text-right text-[11px] text-ink-2">{Math.round(l.distance * WORLD_METRES)} m</td>
                      <td className="num text-right text-[11px] text-ink-2">{l.up ? `${Math.round(l.latencyMs)} ms` : 'jammed'}</td>
                      <td className="num text-right text-[11px] text-ink-2">{l.up ? `${(l.bandwidthKbps / 1000).toFixed(1)} Mb/s` : '—'}</td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          )}
        </section>

        <section>
          <h4 className="label mb-1.5 !text-ink-2">Recent events</h4>
          {events.length === 0 ? <p className="text-[11.5px] text-ink-3">Nothing has involved this node yet.</p> : (
            <ul className="space-y-1">
              {events.map((e) => (
                <li key={e.id} className="flex gap-2 text-[11.5px] leading-snug">
                  <span className="num shrink-0 text-ink-3">T+{e.tick * world.tickSeconds}s</span>
                  <span className="mt-[5px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: SEVERITY_COLOR[e.severity] }} />
                  <span className="text-ink-2">{e.title}</span>
                </li>
              ))}
            </ul>
          )}
        </section>
      </div>

      <footer className="shrink-0 space-y-1.5 border-t border-line bg-bg-2/50 px-3 py-2.5">
        <div className="label">Fault injection</div>
        <div className="flex flex-wrap gap-1.5">
          {node.alive
            ? <Btn size="sm" tone="danger" onClick={() => lab.send({ type: 'failNode', id: node.id })}>Fail node</Btn>
            : <Btn size="sm" tone="primary" onClick={() => lab.send({ type: 'recoverNode', id: node.id })}>Recover node</Btn>}
          <Btn size="sm" disabled={!node.alive} active={node.isolated} onClick={() => lab.send({ type: node.isolated ? 'rejoinNode' : 'isolateNode', id: node.id })}>
            {node.isolated ? 'Restore radio' : 'Jam radio'}
          </Btn>
          <Btn size="sm" onClick={() => lab.send({ type: 'removeNode', id: node.id })} title="Remove this node from the scenario">Remove</Btn>
        </div>
        <div className="flex flex-wrap items-center gap-1.5">
          <select aria-label="Capability to degrade" className="field !h-[22px] !text-[11px]" value={chosen} onChange={(e) => setDim(e.target.value)} disabled={!node.alive}>
            {degradable.map((d) => <option key={d} value={d}>{DIMENSIONS[d]?.label ?? d}</option>)}
          </select>
          <Btn size="sm" disabled={!node.alive || !chosen} onClick={() => lab.send({ type: 'degradeCapability', id: node.id, dim: chosen, factor: 0.5 })}>Degrade −50%</Btn>
          <Btn size="sm" disabled={!node.alive || !altered} onClick={() => lab.send({ type: 'restoreCapabilities', id: node.id })}>Restore</Btn>
        </div>
      </footer>
    </div>
  )
}
