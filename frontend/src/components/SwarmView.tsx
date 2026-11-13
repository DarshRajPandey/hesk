/**
 * Interactive 2D topology view. Everything is drawn in screen pixels from a
 * world→screen transform, so glyphs and labels stay crisp at any zoom level.
 */
import { motion } from 'motion/react'
import { useCallback, useEffect, useMemo, useRef, useState, type PointerEvent as RPointerEvent } from 'react'
import { ARCHETYPES, ARCHETYPE_IDS, COMM_RANGE, WORLD_METRES, type ArchetypeId } from '../sim/catalog'
import type { NodeView, ReplicaView, TaskView, WorldSnapshot } from '../sim/types'
import { lab } from '../state/lab'
import { Btn, cx, Icon, Seg, seriesColor, TASK_STATUS_COLOR } from '../ui/kit'
import { Glyph, GlyphShape } from './glyphs'

interface View { k: number; tx: number; ty: number }
const HOME: View = { k: 1, tx: 0, ty: 0 }
const clamp = (v: number, lo: number, hi: number) => Math.max(lo, Math.min(hi, v))

function hull(points: Array<[number, number]>): Array<[number, number]> {
  if (points.length < 3) return points
  const p = [...points].sort((a, b) => a[0] - b[0] || a[1] - b[1])
  const cross = (o: [number, number], a: [number, number], b: [number, number]) => (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])
  const build = (pts: Array<[number, number]>) => {
    const out: Array<[number, number]> = []
    for (const q of pts) {
      while (out.length >= 2 && cross(out[out.length - 2] as [number, number], out[out.length - 1] as [number, number], q) <= 0) out.pop()
      out.push(q)
    }
    out.pop()
    return out
  }
  return [...build(p), ...build([...p].reverse())]
}

export function SwarmView({ world, selectedId, onSelect, tools = true, className }: {
  world: WorldSnapshot; selectedId: string | null; onSelect: (id: string | null) => void; tools?: boolean; className?: string
}) {
  const wrap = useRef<HTMLDivElement>(null)
  const [size, setSize] = useState({ w: 800, h: 500 })
  const [view, setView] = useState<View>(HOME)
  const [hover, setHover] = useState<string | null>(null)
  const [cursor, setCursor] = useState<{ x: number; y: number } | null>(null)
  const [placing, setPlacing] = useState(false)
  const [archetype, setArchetype] = useState<ArchetypeId>('SCOUT')
  const drag = useRef<{ x: number; y: number; tx: number; ty: number; moved: boolean; hit: string | null } | null>(null)

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const ro = new ResizeObserver(() => setSize({ w: el.clientWidth, h: el.clientHeight }))
    ro.observe(el)
    setSize({ w: el.clientWidth, h: el.clientHeight })
    return () => ro.disconnect()
  }, [])

  const base = Math.max(120, Math.min(size.w, size.h) - 56)
  const sx = useCallback((x: number) => size.w / 2 + (x - 0.5) * base * view.k + view.tx, [size.w, base, view])
  const sy = useCallback((y: number) => size.h / 2 + (y - 0.5) * base * view.k + view.ty, [size.h, base, view])
  const toWorld = useCallback((px: number, py: number) => ({
    x: (px - size.w / 2 - view.tx) / (base * view.k) + 0.5,
    y: (py - size.h / 2 - view.ty) / (base * view.k) + 0.5,
  }), [size, base, view])

  const zoomAt = useCallback((factor: number, px?: number, py?: number) => {
    setView((v) => {
      const k = clamp(v.k * factor, 0.6, 6)
      const cx0 = (px ?? size.w / 2) - size.w / 2
      const cy0 = (py ?? size.h / 2) - size.h / 2
      return { k, tx: cx0 - ((cx0 - v.tx) * k) / v.k, ty: cy0 - ((cy0 - v.ty) * k) / v.k }
    })
  }, [size])

  useEffect(() => {
    const el = wrap.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      e.preventDefault()
      const r = el.getBoundingClientRect()
      zoomAt(Math.exp(-e.deltaY * 0.0016), e.clientX - r.left, e.clientY - r.top)
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [zoomAt])

  const local = (e: RPointerEvent) => {
    const r = (wrap.current as HTMLDivElement).getBoundingClientRect()
    return { px: e.clientX - r.left, py: e.clientY - r.top }
  }
  const onDown = (e: RPointerEvent<SVGSVGElement>) => {
    if (e.button !== 0) return
    // Resolve the node under the pointer before capture retargets later events to the svg.
    const hit = (e.target as Element).closest('[data-node]')?.getAttribute('data-node') ?? null
    e.currentTarget.setPointerCapture(e.pointerId)
    drag.current = { x: e.clientX, y: e.clientY, tx: view.tx, ty: view.ty, moved: false, hit }
  }
  const onMove = (e: RPointerEvent<SVGSVGElement>) => {
    const { px, py } = local(e)
    setCursor(toWorld(px, py))
    const d = drag.current
    if (!d) return
    const dx = e.clientX - d.x
    const dy = e.clientY - d.y
    if (Math.abs(dx) + Math.abs(dy) > 4) d.moved = true
    if (d.moved) setView((v) => ({ ...v, tx: d.tx + dx, ty: d.ty + dy }))
  }
  const onUp = (e: RPointerEvent<SVGSVGElement>) => {
    const d = drag.current
    drag.current = null
    if (!d || d.moved) return
    const { px, py } = local(e)
    const hit = d.hit
    if (hit) {
      onSelect(hit === selectedId ? null : hit)
    } else if (placing) {
      const p = toWorld(px, py)
      if (p.x >= 0 && p.x <= 1 && p.y >= 0 && p.y <= 1) {
        lab.send({ type: 'addNode', archetype, x: Math.round(p.x * 1000) / 1000, y: Math.round(p.y * 1000) / 1000 })
        setPlacing(false)
      }
    } else {
      onSelect(null)
    }
  }

  const nodeById = useMemo(() => new Map(world.nodes.map((n) => [n.id, n])), [world.nodes])
  const replicaIndex = useMemo(() => new Map(world.replicas.map((r, i) => [r.id, i])), [world.replicas])
  const multi = world.replicas.length > 1
  const taskOf = (n: NodeView): { task: TaskView; replica: ReplicaView } | null => {
    if (!n.role) return null
    const replica = world.replicas.find((r) => r.id === n.replicaId)
    const task = replica?.tasks.find((t) => t.taskId === n.role?.taskId)
    return replica && task ? { task, replica } : null
  }
  const focus = hover ?? selectedId
  const focusNode = focus ? nodeById.get(focus) : undefined
  const grid = Array.from({ length: 11 }, (_, i) => i / 10)
  const rangePx = COMM_RANGE * base * view.k
  const showLabels = view.k * base > 300

  return (
    <div ref={wrap} className={cx('relative h-full min-h-[320px] w-full touch-none overflow-hidden bg-bg-0 select-none', className)}>
      <svg
        width={size.w} height={size.h} role="application" aria-label="Swarm topology. Drag to pan, scroll to zoom, select a node to inspect it."
        className={cx('block', placing ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing')}
        onPointerDown={onDown} onPointerMove={onMove} onPointerUp={onUp} onPointerLeave={() => setCursor(null)}
      >
        {/* survey grid, 100 m pitch */}
        <g>
          <rect x={sx(0)} y={sy(0)} width={sx(1) - sx(0)} height={sy(1) - sy(0)} fill="var(--color-bg-1)" stroke="var(--color-line-2)" />
          {grid.slice(1, -1).map((g) => (
            <g key={g} stroke="var(--color-line)" strokeWidth={g === 0.5 ? 1 : 0.6}>
              <line x1={sx(g)} y1={sy(0)} x2={sx(g)} y2={sy(1)} />
              <line x1={sx(0)} y1={sy(g)} x2={sx(1)} y2={sy(g)} />
            </g>
          ))}
          {grid.filter((_, i) => i % 2 === 0).map((g) => (
            <g key={g} className="num" fontSize="9" fill="var(--color-ink-3)">
              <text x={sx(g)} y={sy(1) + 13} textAnchor="middle">{Math.round(g * WORLD_METRES)}</text>
              <text x={sx(0) - 6} y={sy(g) + 3} textAnchor="end">{Math.round(g * WORLD_METRES)}</text>
            </g>
          ))}
          <text x={sx(1)} y={sy(1) + 13} dx={14} className="num" fontSize="9" fill="var(--color-ink-3)">m</text>
        </g>

        {/* partition hulls */}
        {multi && world.replicas.map((r, i) => {
          const pts = hull(r.members.map((id) => nodeById.get(id)).filter((n): n is NodeView => !!n).map((n) => [sx(n.x), sy(n.y)] as [number, number]))
          if (pts.length === 0) return null
          const c = seriesColor(i)
          const d = pts.length === 1 ? `M${pts[0]![0]},${pts[0]![1]}l0.01,0` : `M${pts.map((p) => p.join(',')).join('L')}Z`
          const top = pts.reduce((a, b) => (b[1] < a[1] ? b : a))
          return (
            <g key={r.id}>
              <path d={d} fill={c} fillOpacity={0.05} stroke={c} strokeOpacity={0.09} strokeWidth={64} strokeLinejoin="round" strokeLinecap="round" />
              <text x={top[0]} y={top[1] - 40} textAnchor="middle" className="num" fontSize="10" fill={c}>REPLICA {r.id} · {r.members.length} NODES</text>
            </g>
          )
        })}

        {/* radio range of the focused node */}
        {focusNode?.alive && (
          <circle cx={sx(focusNode.x)} cy={sy(focusNode.y)} r={rangePx} fill="var(--color-accent)" fillOpacity={0.025} stroke="var(--color-accent)" strokeOpacity={0.35} strokeDasharray="2 5" />
        )}

        {/* links */}
        {world.links.map((l) => {
          const a = nodeById.get(l.a)
          const b = nodeById.get(l.b)
          if (!a || !b) return null
          const hot = focus === l.a || focus === l.b
          const q = l.bandwidthKbps / 12000
          return (
            <g key={`${l.a}|${l.b}`}>
              <line
                x1={sx(a.x)} y1={sy(a.y)} x2={sx(b.x)} y2={sy(b.y)}
                stroke={!l.up ? 'var(--color-crit)' : hot ? 'var(--color-accent)' : 'var(--color-ink-2)'}
                strokeOpacity={!l.up ? 0.5 : hot ? 0.9 : 0.14 + q * 0.4} strokeWidth={hot ? 1.3 : 0.6 + q * 0.9}
                strokeDasharray={l.up ? undefined : '2 5'}
              />
              {hot && l.up && (
                <text x={(sx(a.x) + sx(b.x)) / 2} y={(sy(a.y) + sy(b.y)) / 2 - 4} textAnchor="middle" className="num" fontSize="9" fill="var(--color-accent)"
                  stroke="var(--color-bg-1)" strokeWidth={3} paintOrder="stroke">
                  {Math.round(l.latencyMs)} ms · {(l.bandwidthKbps / 1000).toFixed(1)} Mb/s
                </text>
              )}
            </g>
          )
        })}

        {/* coalition data flows */}
        {world.replicas.flatMap((r) => r.tasks.filter((t) => t.kind === 'COALITION' && t.status !== 'ABANDONED').map((t) => {
          const ms = t.members.map((id) => nodeById.get(id)).filter((n): n is NodeView => !!n)
          return (
            <g key={`${r.id}-${t.taskId}`} stroke="var(--color-violet)" fill="none">
              {ms.slice(1).map((m, i) => (
                <line key={m.id} x1={sx(ms[i]!.x)} y1={sy(ms[i]!.y)} x2={sx(m.x)} y2={sy(m.y)} strokeOpacity={0.25} strokeWidth={7} strokeLinecap="round" />
              ))}
              {t.flows.filter((f) => f.sourceNode !== f.sinkNode).map((f, i) => {
                const a = nodeById.get(f.sourceNode)
                const b = nodeById.get(f.sinkNode)
                return a && b ? <line key={i} className="flow-line" x1={sx(a.x)} y1={sy(a.y)} x2={sx(b.x)} y2={sy(b.y)} strokeWidth={1.6} strokeOpacity={t.live ? 1 : 0.4} /> : null
              })}
            </g>
          )
        }))}

        {/* jamming line */}
        {world.cut && (
          <g stroke="var(--color-crit)" fill="var(--color-crit)">
            {world.cut.axis === 'x'
              ? <line x1={sx(world.cut.at)} y1={sy(0) - 10} x2={sx(world.cut.at)} y2={sy(1) + 10} strokeWidth={1.2} strokeDasharray="6 4" />
              : <line x1={sx(0) - 10} y1={sy(world.cut.at)} x2={sx(1) + 10} y2={sy(world.cut.at)} strokeWidth={1.2} strokeDasharray="6 4" />}
            <text x={world.cut.axis === 'x' ? sx(world.cut.at) + 6 : sx(0) + 6} y={world.cut.axis === 'x' ? sy(0) + 12 : sy(world.cut.at) - 6} className="num" fontSize="9" stroke="none">JAMMING LINE</text>
          </g>
        )}

        {/* nodes */}
        {world.nodes.map((n) => {
          const x = sx(n.x)
          const y = sy(n.y)
          const ri = n.replicaId ? replicaIndex.get(n.replicaId) ?? 0 : 0
          const rt = taskOf(n)
          const stroke = !n.alive ? 'var(--color-ink-3)' : n.depleted ? 'var(--color-warn)' : multi ? seriesColor(ri) : '#c5d1dc'
          const selected = n.id === selectedId
          const statusColor = rt ? TASK_STATUS_COLOR[rt.task.status] ?? 'var(--color-ink-3)' : 'var(--color-ink-3)'
          const stale = !!rt && !rt.task.live
          return (
            <g
              key={n.id} data-node={n.id} transform={`translate(${x},${y})`} className="cursor-pointer" role="button" tabIndex={0}
              aria-label={`${n.id}, ${ARCHETYPES[n.archetype].label}, ${n.health.toLowerCase()}${rt ? `, executing ${rt.task.name}` : ', idle'}`}
              aria-pressed={selected}
              onPointerEnter={() => setHover(n.id)} onPointerLeave={() => setHover(null)}
              onKeyDown={(e) => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); onSelect(selected ? null : n.id) } }}
            >
              <circle r={20} fill="transparent" />
              {n.alive && <motion.circle key={world.tick} r={10} fill="none" stroke={stroke} initial={{ scale: 1, opacity: 0.45 }} animate={{ scale: 2.3, opacity: 0 }} transition={{ duration: 0.9, ease: 'easeOut' }} />}
              {selected && <circle r={18} fill="none" stroke="var(--color-accent)" strokeWidth={1} />}
              {selected && <path d="M-23 0h5M18 0h5M0 -23v5M0 18v5" stroke="var(--color-accent)" strokeWidth={1} />}
              <g
                fill={!n.alive ? 'var(--color-bg-1)' : rt ? `color-mix(in oklab, ${stroke} 26%, var(--color-bg-1))` : 'var(--color-bg-1)'}
                stroke={stroke} strokeWidth={1.6} strokeLinejoin="round" strokeDasharray={n.alive ? undefined : '3 3'}
                style={{ transition: 'fill 240ms, stroke 240ms' }}
              >
                <GlyphShape archetype={n.archetype} r={9} />
              </g>
              {n.archetype === 'RELAY' && n.alive && <circle r={2.2} fill={stroke} />}
              {!n.alive && <path d="M-5 -5l10 10M5 -5l-10 10" stroke="var(--color-crit)" strokeWidth={1.6} />}
              {n.isolated && <circle r={14} fill="none" stroke="var(--color-crit)" strokeDasharray="2 3" />}
              {n.health === 'DEGRADED' && <circle cx={10} cy={-10} r={3} fill="var(--color-warn)" stroke="var(--color-bg-1)" />}
              {showLabels && (
                <text y={24} textAnchor="middle" className="num" fontSize="10" fill={n.alive ? 'var(--color-ink-2)' : 'var(--color-ink-3)'} stroke="var(--color-bg-1)" strokeWidth={3} paintOrder="stroke">
                  {n.id}
                </text>
              )}
              {n.alive && (
                <g transform="translate(-9,29)">
                  <rect width={18} height={2} fill="var(--color-bg-3)" />
                  <rect width={18 * n.energy} height={2} fill={n.energy < 0.25 ? 'var(--color-warn)' : 'var(--color-ink-3)'} />
                </g>
              )}
              {rt && (
                <g transform="translate(0,-21)">
                  <rect x={-21} y={-8} width={42} height={13} rx={1.5} fill="var(--color-bg-0)" stroke={statusColor} strokeOpacity={0.8} strokeDasharray={stale ? '2 2' : undefined} />
                  <text textAnchor="middle" y={2} className="num" fontSize="9" fill={statusColor}>{rt.task.code}·T{rt.task.tier}</text>
                </g>
              )}
            </g>
          )
        })}
      </svg>

      {/* overlays */}
      {tools && (
        <div className="absolute top-2 left-2 flex max-w-[calc(100%-1rem)] flex-wrap items-center gap-1.5">
          <div className="flex items-center gap-1 rounded-[3px] border border-line bg-bg-1/95 p-1">
            <select aria-label="Agent type to add" className="field !h-[22px] !text-[11px]" value={archetype} onChange={(e) => setArchetype(e.target.value as ArchetypeId)}>
              {ARCHETYPE_IDS.map((a) => <option key={a} value={a}>{ARCHETYPES[a].label}</option>)}
            </select>
            <Btn size="sm" onClick={() => lab.send({ type: 'addNode', archetype })} title="Add a node at an automatically chosen position in radio range"><Icon name="plus" size={11} />Add</Btn>
            <Btn size="sm" active={placing} onClick={() => setPlacing((p) => !p)} title="Click on the map to place the node">Place</Btn>
          </div>
          <div className="flex items-center gap-1 rounded-[3px] border border-line bg-bg-1/95 p-1">
            <span className="label px-1">Jam</span>
            <Btn size="sm" active={world.cut?.axis === 'x'} onClick={() => lab.send({ type: 'setCut', axis: 'x', at: 0.5 })} title="Jam every link crossing the east/west line">E | W</Btn>
            <Btn size="sm" active={world.cut?.axis === 'y'} onClick={() => lab.send({ type: 'setCut', axis: 'y', at: 0.5 })} title="Jam every link crossing the north/south line">N | S</Btn>
            <Btn size="sm" disabled={!world.cut} onClick={() => lab.send({ type: 'clearCut' })}>Lift</Btn>
          </div>
          <div className="flex items-center gap-1 rounded-[3px] border border-line bg-bg-1/95 p-1">
            <span className="label px-1">Latency</span>
            <Seg label="Link latency multiplier" value={world.latencyFactor} onChange={(f) => lab.send({ type: 'setLatencyFactor', factor: f })}
              options={[{ value: 1, label: '×1' }, { value: 2, label: '×2' }, { value: 4, label: '×4' }]} />
          </div>
        </div>
      )}
      {placing && <div className="num absolute top-11 left-2 rounded-[2px] border border-accent/50 bg-bg-1 px-2 py-1 text-[11px] text-accent">Click inside the survey area to place a {ARCHETYPES[archetype].label.toLowerCase()}</div>}

      <div className="pointer-events-none absolute bottom-2 left-2 flex flex-wrap items-center gap-x-3 gap-y-1 rounded-[3px] border border-line bg-bg-1/95 px-2 py-1.5">
        {ARCHETYPE_IDS.map((a) => (
          <span key={a} className="flex items-center gap-1 text-[10.5px] text-ink-2"><Glyph archetype={a} size={12} color="#c5d1dc" />{ARCHETYPES[a].label}</span>
        ))}
        <span className="flex items-center gap-1 text-[10.5px] text-ink-2"><svg width="18" height="6"><line x1="0" y1="3" x2="18" y2="3" stroke="var(--color-violet)" strokeWidth="1.6" strokeDasharray="4 3" /></svg>data flow</span>
      </div>

      <div className="absolute right-2 bottom-2 flex flex-col overflow-hidden rounded-[3px] border border-line bg-bg-1/95">
        <button type="button" aria-label="Zoom in" className="flex h-7 w-7 items-center justify-center text-ink-2 hover:bg-bg-3 hover:text-ink" onClick={() => zoomAt(1.3)}><Icon name="plus" /></button>
        <button type="button" aria-label="Zoom out" className="flex h-7 w-7 items-center justify-center border-t border-line text-ink-2 hover:bg-bg-3 hover:text-ink" onClick={() => zoomAt(1 / 1.3)}><Icon name="minus" /></button>
        <button type="button" aria-label="Reset view" className="flex h-7 w-7 items-center justify-center border-t border-line text-ink-2 hover:bg-bg-3 hover:text-ink" onClick={() => setView(HOME)}><Icon name="fit" /></button>
      </div>

      <div className="num pointer-events-none absolute top-2 right-2 rounded-[2px] bg-bg-1/90 px-1.5 py-0.5 text-[10px] text-ink-3">
        {cursor && cursor.x >= 0 && cursor.x <= 1 && cursor.y >= 0 && cursor.y <= 1
          ? `E ${Math.round(cursor.x * WORLD_METRES).toString().padStart(4, '0')}  N ${Math.round((1 - cursor.y) * WORLD_METRES).toString().padStart(4, '0')} m`
          : `zoom ${view.k.toFixed(2)}×`}
        {world.pendingDetection !== null && <span className="ml-2 text-warn">change undetected · {world.pendingDetection} beacon{world.pendingDetection === 1 ? '' : 's'}</span>}
      </div>
    </div>
  )
}
