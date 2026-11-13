import { describe, expect, it } from 'vitest'
import { SimEngine } from '../src/sim/engine'
import { EXPERIMENTS } from '../src/sim/experiments'
import type { Command, WorldSnapshot } from '../src/sim/types'

const strip = (s: WorldSnapshot) => JSON.stringify({ ...s, reconciliations: s.reconciliations.map((r) => ({ ...r, wallMs: 0 })) })
const steps = (e: SimEngine, n: number) => { for (let i = 0; i < n; i++) e.dispatch({ type: 'step' }) }
const last = (e: SimEngine) => e.snapshot.metrics.at(-1)!
const task = (e: SimEngine, id: string, replica = 0) => e.snapshot.replicas[replica]!.tasks.find((t) => t.taskId === id)!

function runExperiment(id: string): { engine: SimEngine; trace: number[] } {
  const def = EXPERIMENTS.find((x) => x.id === id)!
  const e = new SimEngine(def.preset, def.seed)
  const memo: Record<string, string> = {}
  const trace: number[] = []
  for (let t = 0; t <= def.duration; t++) {
    for (const s of def.steps.filter((x) => x.at === t)) {
      const cmd = s.command?.(e.snapshot, memo)
      if (cmd) e.dispatch(cmd)
    }
    trace.push(last(e).utilityRatio)
    if (t < def.duration) e.dispatch({ type: 'step' })
  }
  return { engine: e, trace }
}

describe('simulation engine', () => {
  it('is deterministic for a fixed seed and command sequence', () => {
    const script: Command[] = [
      { type: 'step' }, { type: 'failNode', id: 'ISR-1' }, { type: 'step' }, { type: 'step' }, { type: 'step' },
      { type: 'addNode', archetype: 'SCOUT' }, { type: 'setCut', axis: 'x', at: 0.5 }, { type: 'step' }, { type: 'step' }, { type: 'step' },
      { type: 'clearCut' }, { type: 'step' }, { type: 'step' }, { type: 'step' },
    ]
    const run = () => { const e = new SimEngine('baseline', 11); script.forEach((c) => e.dispatch(c)); return strip(e.snapshot) }
    expect(run()).toBe(run())
    const other = new SimEngine('baseline', 12)
    script.forEach((c) => other.dispatch(c))
    expect(strip(other.snapshot)).not.toBe(run())
  })

  it('boots one replica that owns every task', () => {
    const e = new SimEngine('baseline', 7)
    expect(e.snapshot.replicas).toHaveLength(1)
    expect(last(e).utilityRatio).toBe(1)
    const owners = e.snapshot.replicas[0]!.tasks.flatMap((t) => t.members)
    expect(new Set(owners).size).toBe(owners.length)
  })

  it('acts on a node failure only after the detection delay', () => {
    const e = new SimEngine('baseline', 7)
    const mapper = task(e, 'map_zone').members[0]!
    e.dispatch({ type: 'failNode', id: mapper })
    expect(task(e, 'map_zone').members).toEqual([mapper])
    expect(task(e, 'map_zone').live).toBe(false)
    expect(last(e).utilityRatio).toBeLessThan(1)
    steps(e, e.snapshot.detectTicks)
    expect(task(e, 'map_zone').members).not.toContain(mapper)
    expect(task(e, 'map_zone').kind).toBe('COALITION')
    expect(last(e).utilityRatio).toBe(1)
  })

  it('forks on partition, duplicates work, and converges on heal', () => {
    const e = new SimEngine('baseline', 7)
    steps(e, 2)
    e.dispatch({ type: 'setCut', axis: 'x', at: 0.5 })
    steps(e, 4)
    expect(e.snapshot.replicas).toHaveLength(2)
    expect(last(e).agreement).toBeLessThan(1)
    expect(last(e).duplicated).toBeGreaterThan(0)
    const [a, b] = e.snapshot.replicas
    expect(a!.members.filter((m) => b!.members.includes(m))).toEqual([])
    e.dispatch({ type: 'clearCut' })
    steps(e, 3)
    expect(e.snapshot.replicas).toHaveLength(1)
    const rec = e.snapshot.reconciliations.at(-1)!
    expect(rec.conflicts.some((c) => c.type === 'EXCLUSIVE_OWNERSHIP')).toBe(true)
    expect(rec.converged).toBe(true)
    expect(last(e).agreement).toBe(1)
    const owners = e.snapshot.replicas[0]!.tasks.flatMap((t) => t.members)
    expect(new Set(owners).size).toBe(owners.length)
  })

  it('removes and adds nodes', () => {
    const e = new SimEngine('quintet', 7)
    e.dispatch({ type: 'addNode', archetype: 'LIDAR' })
    expect(e.snapshot.nodes).toHaveLength(6)
    e.dispatch({ type: 'removeNode', id: 'THM-1' })
    expect(e.snapshot.nodes.map((n) => n.id)).not.toContain('THM-1')
    steps(e, 3)
    expect(e.snapshot.replicas[0]!.members).toContain('LDR-1')
  })

  it.each(EXPERIMENTS.map((x) => [x.id]))('experiment %s degrades and then recovers', (id) => {
    const { engine, trace } = runExperiment(id)
    const start = trace[0]!
    const end = trace.at(-1)!
    if (id === 'join') expect(end).toBeGreaterThan(start)
    else if (id !== 'partition') expect(Math.min(...trace)).toBeLessThan(end)
    expect(end).toBeGreaterThanOrEqual(id === 'latency' ? trace[2]! : start)
    expect(engine.snapshot.replicas).toHaveLength(1)
    expect(engine.snapshot.faults.every((f) => f.respondedTick !== null)).toBe(true)
  })
})
