/**
 * Deterministic demonstration harness around the ported HESK kernel.
 *
 * What is kernel and what is harness:
 *  - Matching, bidding, coalition formation, degradation planning, ledger merge
 *    and partition reconciliation are the ported kernel algorithms (src/kernel).
 *  - Everything that makes them run as a system is this harness: the world
 *    model, link physics, failure detection delay, when triggers fire, how a
 *    plan is applied, and how replicas fork and merge. HESK itself ships no
 *    runtime, transport or simulator, so none of that is "real HESK" behaviour.
 *
 * Simplification: one coordination ledger is kept per connected component
 * ("replica") rather than per node; nodes inside a component are assumed to be
 * in sync. Replicas never read each other's state or any global truth.
 */
import { computeScarcityPenalty, computeSystemCost, evaluateBids, type Bid } from '../kernel/allocation'
import { formCoalition, type Coalition } from '../kernel/coalition'
import {
  attemptUpgrades, AvailableNodes, computeSwarmUtility, currentQuality, handleDegradationTrigger,
  type ActiveTask, type DegradationContext, type DegradationLedger, type DegradationPlan, type DegradationTrigger,
} from '../kernel/degradation'
import { LocalStateLedger, valuesEqual } from '../kernel/ledger'
import { computeFullMatch, computeMatchQuality } from '../kernel/matching'
import { getUnseenEvents, handleReconnection, type SideEffect } from '../kernel/reconciliation'
import { TaskStatus, type CapabilityState, type DimValue, type LinkMetrics, type PriorityClass, type TaskDefinition } from '../kernel/types'
import {
  ARCHETYPES, buildPresetNodes, COMM_RANGE, distance, linkBandwidth, linkLatency, PRESETS, taskById,
  type ArchetypeId, type PresetId,
} from './catalog'
import { Rng } from './rng'
import type {
  AuctionRound, Command, ConflictView, EventKind, FaultKind, FaultRecord, Health, LedgerRow, LinkView, MetricSample, NodeView,
  ReconciliationRecord, ReplicaView, Severity, SimEvent, Source, TaskView, WorldSnapshot,
} from './types'

export const TICK_SECONDS = 5
/** Beacons missed before a replica acts on a topology change. A harness parameter, not a kernel one. */
export const DETECT_TICKS = 2
const PROGRESS_RATE = 0.02
const DRAIN_WORK = 0.004
const DRAIN_IDLE = 0.001
const ENERGY_CRITICAL = 0.1
const BASE_CONSUMPTION = 0.1
const MAX_EVENTS = 400
const MAX_AUCTIONS = 80
const MAX_METRICS = 1200
const PRIORITY_RANK: Record<PriorityClass, number> = { CRITICAL: 3, IMPORTANT: 2, OPTIONAL: 1 }

interface SimNode {
  id: string
  archetype: ArchetypeId
  x: number
  y: number
  dims: Record<string, DimValue>
  baseDims: Record<string, DimValue>
  energy: number
  alive: boolean
  removed: boolean
  depleted: boolean
  replicaId: string | null
  joinedTick: number
}

interface RTask extends ActiveTask {
  progress: number
  matchQuality: number
}

const membersOf = (t: ActiveTask): string[] =>
  t.assignee === null ? [] : typeof t.assignee === 'string' ? [t.assignee] : t.assignee.members
const isActive = (t: ActiveTask) => t.status === TaskStatus.EXECUTING || t.status === TaskStatus.DEGRADED
const ownerKey = (taskId: string) => `task_owner.${taskId}`
const round4 = (n: number) => Math.round(n * 1e4) / 1e4

class Replica implements DegradationLedger {
  members = new Set<string>()
  tasks = new Map<string, RTask>()
  affected: RTask[] = []
  needsReplan = false
  constructor(public id: string, public ledger: LocalStateLedger) {}
  getAffectedTasks(): ActiveTask[] {
    return [...this.affected]
  }
  getAllActiveTasks(): ActiveTask[] {
    return [...this.tasks.values()]
  }
  releaseTaskResources(task: ActiveTask): string[] {
    return membersOf(task)
  }
  byPriority(): RTask[] {
    return [...this.tasks.values()].sort((a, b) =>
      PRIORITY_RANK[b.def.priorityClass] - PRIORITY_RANK[a.def.priorityClass] || b.def.missionPriority - a.def.missionPriority)
  }
}

export class SimEngine {
  private nodes = new Map<string, SimNode>()
  private replicas = new Map<string, Replica>()
  private rng = new Rng(1)
  private preset: PresetId = 'baseline'
  private seed = 1
  private tick = 0
  private taskDefs: TaskDefinition[] = []
  private cut: { axis: 'x' | 'y'; at: number } | null = null
  private isolated = new Set<string>()
  private latencyFactor = 1
  private topoDirtySince: number | null = null
  private events: SimEvent[] = []
  private metrics: MetricSample[] = []
  private auctions: AuctionRound[] = []
  private reconciliations: ReconciliationRecord[] = []
  private faults: FaultRecord[] = []
  private ids = { event: 0, replica: 0, coalition: 0, auction: 0, recon: 0, fault: 0 }
  private archetypeCount: Partial<Record<ArchetypeId, number>> = {}
  private msg = { beacon: 0, coordination: 0, reconcile: 0 }
  private responded = false
  private snap!: WorldSnapshot

  constructor(preset: PresetId = 'baseline', seed = 7) {
    this.reset(preset, seed)
  }

  get snapshot(): WorldSnapshot {
    return this.snap
  }

  dispatch(cmd: Command): void {
    switch (cmd.type) {
      case 'step': this.step(); break
      case 'reset': this.reset(cmd.preset, cmd.seed); return
      case 'addNode': this.addNode(cmd.archetype, cmd.x, cmd.y); break
      case 'removeNode': this.failNode(cmd.id, true); break
      case 'failNode': this.failNode(cmd.id, false); break
      case 'recoverNode': this.recoverNode(cmd.id); break
      case 'degradeCapability': this.degradeCapability(cmd.id, cmd.dim, cmd.factor); break
      case 'restoreCapabilities': this.restoreCapabilities(cmd.id); break
      case 'setCut': this.setCut(cmd.axis, cmd.at); break
      case 'clearCut': this.clearCut(); break
      case 'isolateNode': this.setIsolated(cmd.id, true); break
      case 'rejoinNode': this.setIsolated(cmd.id, false); break
      case 'setLatencyFactor': this.setLatency(cmd.factor); break
    }
    this.settleFaults()
    if (cmd.type !== 'step') this.replaceLastSample()
    this.snap = this.build()
  }

  // ─── lifecycle ──────────────────────────────────────────────────────

  private reset(preset: PresetId, seed: number): void {
    this.preset = preset
    this.seed = seed
    this.rng = new Rng(seed)
    this.tick = 0
    this.nodes.clear()
    this.replicas.clear()
    this.cut = null
    this.isolated.clear()
    this.latencyFactor = 1
    this.topoDirtySince = null
    this.events = []
    this.metrics = []
    this.auctions = []
    this.reconciliations = []
    this.faults = []
    this.ids = { event: 0, replica: 0, coalition: 0, auction: 0, recon: 0, fault: 0 }
    this.archetypeCount = {}
    this.msg = { beacon: 0, coordination: 0, reconcile: 0 }
    this.taskDefs = PRESETS[preset].tasks.map(taskById)
    for (const s of buildPresetNodes(preset)) {
      this.archetypeCount[s.archetype] = (this.archetypeCount[s.archetype] ?? 0) + 1
      this.nodes.set(s.id, {
        ...s, baseDims: { ...s.dims }, energy: round4(this.rng.range(0.8, 1)), alive: true, removed: false, depleted: false,
        replicaId: null, joinedTick: 0,
      })
    }
    this.log('BOOT', 'info', 'harness', `Scenario "${PRESETS[preset].label}" initialised`, {
      detail: `seed ${seed} · ${this.nodes.size} nodes · ${this.taskDefs.length} mission tasks`,
    })
    this.syncTopology()
    this.metrics.push(this.sample())
    this.snap = this.build()
  }

  private step(): void {
    this.tick += 1
    this.msg = { beacon: 0, coordination: 0, reconcile: 0 }
    const comp = this.componentIndex()

    for (const r of this.sortedReplicas()) {
      for (const t of r.tasks.values()) {
        if (!isActive(t) || !this.isLive(t, comp) || t.progress >= 1) continue
        t.progress = round4(Math.min(1, t.progress + PROGRESS_RATE * currentQuality(t)))
        this.recordOwner(r, t)
      }
      const beacons = r.ledger.entries.get('beacons')
      r.ledger.writeLocal('beacons', Number(beacons?.value ?? 0) + r.members.size, 'COUNTER')
    }

    for (const n of this.liveNodes()) {
      const working = this.roleOf(n) !== null
      n.energy = round4(Math.max(0, n.energy - (working ? DRAIN_WORK : DRAIN_IDLE)))
      if (n.energy <= ENERGY_CRITICAL && !n.depleted) this.onEnergyCritical(n)
    }

    this.msg.beacon = this.upLinkCount() * 2
    if (this.topoDirtySince !== null && this.tick - this.topoDirtySince >= DETECT_TICKS) this.syncTopology()
    this.settleFaults()
    this.metrics.push(this.sample())
    if (this.metrics.length > MAX_METRICS) this.metrics.shift()
  }

  // ─── operator commands ──────────────────────────────────────────────

  private addNode(archetype: ArchetypeId, x?: number, y?: number): void {
    const a = ARCHETYPES[archetype]
    const k = (this.archetypeCount[archetype] ?? 0) + 1
    this.archetypeCount[archetype] = k
    const id = `${a.prefix}-${k}`
    const pos = x !== undefined && y !== undefined ? { x, y } : this.findPlacement()
    const dims: Record<string, DimValue> = {}
    for (const [d, v] of Object.entries(a.dims)) {
      dims[d] = typeof v === 'number' ? round4(Math.min(d === 'compute' ? 10 : 1, v * this.rng.range(0.95, 1.05))) : v
    }
    this.nodes.set(id, {
      id, archetype, ...pos, dims, baseDims: { ...dims }, energy: round4(this.rng.range(0.9, 1)), alive: true, removed: false,
      depleted: false, replicaId: null, joinedTick: this.tick,
    })
    this.openFault('JOIN', `${id} powered on`, [id])
    this.log('JOIN', 'info', 'operator', `${id} (${a.label}) powered on`, {
      nodeIds: [id], detail: `Will be discovered after ${DETECT_TICKS} beacon intervals if in radio range.`,
    })
    this.markDirty()
  }

  /** Deterministic placement inside radio range of an existing live node, away from others. */
  private findPlacement(): { x: number; y: number } {
    const live = this.liveNodes()
    let best = { x: 0.5, y: 0.5 }
    let bestScore = -1
    for (let i = 0; i < 40; i++) {
      const p = { x: round4(this.rng.range(0.08, 0.92)), y: round4(this.rng.range(0.08, 0.92)) }
      const ds = live.map((n) => distance(n, p))
      const nearest = ds.length ? Math.min(...ds) : 0.2
      const score = nearest > COMM_RANGE * 0.9 ? 0 : nearest
      if (score > bestScore) {
        bestScore = score
        best = p
      }
    }
    return best
  }

  private failNode(id: string, remove: boolean): void {
    const n = this.nodes.get(id)
    if (!n || n.removed || (!n.alive && !remove)) return
    const wasAlive = n.alive
    if (wasAlive) this.openFault(remove ? 'REMOVE' : 'NODE_FAILURE', remove ? `${id} removed` : `${id} failed`, [id])
    n.alive = false
    n.removed = remove
    this.isolated.delete(id)
    if (wasAlive) {
      this.log('FAULT', 'crit', 'operator', remove ? `${id} removed from the swarm` : `${id} failed`, {
        nodeIds: [id], detail: `Peers keep their last belief until ${DETECT_TICKS} beacons are missed.`,
      })
      this.markDirty()
    }
  }

  private recoverNode(id: string): void {
    const n = this.nodes.get(id)
    if (!n || n.alive || n.removed) return
    n.alive = true
    n.depleted = false
    n.energy = Math.max(n.energy, 0.6)
    // If peers never noticed the outage, the node simply resumes in its replica.
    n.replicaId = this.sortedReplicas().find((r) => r.members.has(id))?.id ?? null
    this.openFault('RECOVERY', `${id} recovered`, [id])
    this.log('RECOVERY', 'ok', 'operator', `${id} back online`, {
      nodeIds: [id], detail: 'Rejoins with an empty ledger; state is transferred when a peer hears its beacon.',
    })
    this.markDirty()
  }

  private degradeCapability(id: string, dim: string, factor: number): void {
    const n = this.nodes.get(id)
    if (!n || !n.alive) return
    const v = n.dims[dim]
    if (v === undefined) return
    this.openFault('CAPABILITY', `${id} ${dim} degraded`, [id])
    n.dims = { ...n.dims, [dim]: typeof v === 'number' ? round4(v * factor) : typeof v === 'boolean' ? false : v }
    this.log('FAULT', 'warn', 'operator', `${id} reports degraded ${dim}`, {
      nodeIds: [id], detail: `${String(v)} → ${String(n.dims[dim])}. Self-reported, so peers react without detection delay.`,
    })
    const r = n.replicaId ? this.replicas.get(n.replicaId) : undefined
    if (!r) return
    const affected = [...r.tasks.values()].filter((t) => isActive(t) && membersOf(t).includes(id) && !this.stillSatisfied(r, t))
    this.responded = true
    if (affected.length > 0) this.runTrigger(r, { triggerType: 'CAPABILITY_DEGRADATION', sourceNode: id }, affected)
    this.replan(r, 'capability change')
  }

  private restoreCapabilities(id: string): void {
    const n = this.nodes.get(id)
    if (!n || !n.alive) return
    n.dims = { ...n.baseDims }
    this.openFault('RECOVERY', `${id} capabilities restored`, [id])
    this.log('RECOVERY', 'ok', 'operator', `${id} capabilities restored`, { nodeIds: [id] })
    const r = n.replicaId ? this.replicas.get(n.replicaId) : undefined
    this.responded = true
    if (r) this.replan(r, 'capability restored')
  }

  private setCut(axis: 'x' | 'y', at: number): void {
    this.openFault('PARTITION', `Links jammed across ${axis === 'x' ? 'east/west' : 'north/south'} line`, [])
    this.cut = { axis, at }
    this.log('PARTITION', 'crit', 'operator', `Jamming line placed (${axis === 'x' ? 'E/W' : 'N/S'} at ${at.toFixed(2)})`, {
      detail: 'Every link crossing the line is down.',
    })
    this.markDirty()
  }

  private clearCut(): void {
    if (!this.cut) return
    this.cut = null
    this.openFault('HEAL', 'Jamming lifted', [])
    this.log('RECOVERY', 'ok', 'operator', 'Jamming lifted — crossing links restored')
    this.markDirty()
  }

  private setIsolated(id: string, on: boolean): void {
    const n = this.nodes.get(id)
    if (!n || !n.alive || this.isolated.has(id) === on) return
    this.openFault(on ? 'PARTITION' : 'HEAL', on ? `${id} radio jammed` : `${id} radio restored`, [id])
    if (on) this.isolated.add(id)
    else this.isolated.delete(id)
    this.log(on ? 'PARTITION' : 'RECOVERY', on ? 'crit' : 'ok', 'operator', on ? `${id} radio jammed — all its links down` : `${id} radio restored`, { nodeIds: [id] })
    this.markDirty()
  }

  private setLatency(factor: number): void {
    const prev = this.latencyFactor
    if (factor === prev) return
    this.latencyFactor = factor
    this.openFault('LATENCY', `Link latency ×${factor}`, [])
    this.log('FAULT', factor > prev ? 'warn' : 'ok', 'operator', `Link latency scaled ×${factor}`, {
      detail: 'Latency only matters to the kernel through coalition data-flow limits (max_latency_ms).',
    })
    this.responded = true
    for (const r of this.sortedReplicas()) {
      if (factor > prev) {
        const affected = [...r.tasks.values()].filter((t) => isActive(t) && !this.flowsFeasible(r, t))
        if (affected.length > 0) this.runTrigger(r, { triggerType: 'LINK_LOSS', sourceNode: '<link>' }, affected)
      } else {
        this.replan(r, 'latency improved')
      }
    }
  }

  // ─── physics ────────────────────────────────────────────────────────

  private liveNodes(): SimNode[] {
    return [...this.nodes.values()].filter((n) => n.alive)
  }

  private jammed(a: SimNode, b: SimNode): boolean {
    if (this.isolated.has(a.id) || this.isolated.has(b.id)) return true
    if (!this.cut) return false
    const side = (n: SimNode) => (this.cut?.axis === 'x' ? n.x : n.y) < (this.cut?.at ?? 0)
    return side(a) !== side(b)
  }

  private linkUp(a: SimNode, b: SimNode): boolean {
    return a.alive && b.alive && distance(a, b) <= COMM_RANGE && !this.jammed(a, b)
  }

  private upLinkCount(): number {
    const live = this.liveNodes()
    let c = 0
    for (let i = 0; i < live.length; i++) for (let j = i + 1; j < live.length; j++) if (this.linkUp(live[i] as SimNode, live[j] as SimNode)) c++
    return c
  }

  /** Connected components of the physical radio graph, each sorted by id. */
  private components(): string[][] {
    const live = this.liveNodes().sort((a, b) => (a.id < b.id ? -1 : 1))
    const seen = new Set<string>()
    const out: string[][] = []
    for (const start of live) {
      if (seen.has(start.id)) continue
      const comp: string[] = []
      const queue = [start]
      seen.add(start.id)
      while (queue.length) {
        const cur = queue.shift() as SimNode
        comp.push(cur.id)
        for (const o of live) {
          if (!seen.has(o.id) && this.linkUp(cur, o)) {
            seen.add(o.id)
            queue.push(o)
          }
        }
      }
      out.push(comp.sort())
    }
    return out
  }

  private componentIndex(): Map<string, number> {
    const m = new Map<string, number>()
    this.components().forEach((c, i) => c.forEach((id) => m.set(id, i)))
    return m
  }

  private isLive(t: ActiveTask, comp: Map<string, number>): boolean {
    const ms = membersOf(t)
    if (!isActive(t) || ms.length === 0) return false
    const c0 = comp.get(ms[0] as string)
    return c0 !== undefined && ms.every((m) => comp.get(m) === c0)
  }

  /** Link quality as a replica can measure it: only between its own members over live links. */
  private linksFor(r: Replica): LinkMetrics {
    const pair = (a: string, b: string): [SimNode, SimNode] | null => {
      const na = this.nodes.get(a)
      const nb = this.nodes.get(b)
      return na && nb && r.members.has(a) && r.members.has(b) && this.linkUp(na, nb) ? [na, nb] : null
    }
    return {
      getBandwidth: (a, b) => {
        const p = pair(a, b)
        return p ? linkBandwidth(distance(p[0], p[1])) : 0
      },
      getLatency: (a, b) => {
        const p = pair(a, b)
        return p ? linkLatency(distance(p[0], p[1])) * this.latencyFactor : Infinity
      },
    }
  }

  private ctx(r: Replica): DegradationContext {
    return { linkMetrics: this.linksFor(r), now: this.tick * TICK_SECONDS, nextCoalitionId: () => `coal-${++this.ids.coalition}` }
  }

  private state(id: string): CapabilityState {
    const n = this.nodes.get(id) as SimNode
    return { nodeId: id, timestamp: this.tick * TICK_SECONDS, dimensions: n.dims }
  }

  private usable(r: Replica): string[] {
    return [...r.members].sort().filter((id) => {
      const n = this.nodes.get(id)
      return n !== undefined && !n.depleted
    })
  }

  private freeStates(r: Replica): CapabilityState[] {
    const busy = new Set<string>()
    for (const t of r.tasks.values()) if (isActive(t)) membersOf(t).forEach((m) => busy.add(m))
    return this.usable(r).filter((id) => !busy.has(id)).map((id) => this.state(id))
  }

  private roleOf(n: SimNode): RTask | null {
    const r = n.replicaId ? this.replicas.get(n.replicaId) : undefined
    if (!r) return null
    for (const t of r.tasks.values()) if (isActive(t) && membersOf(t).includes(n.id)) return t
    return null
  }

  private stillSatisfied(r: Replica, t: RTask): boolean {
    const tier = t.def.tiers[t.currentTier]
    if (!tier) return false
    if (typeof t.assignee === 'string') return computeFullMatch(this.state(t.assignee), tier.required, tier.preferred).eligible
    if (t.assignee === null) return false
    const res = formCoalition({
      taskId: t.def.taskId, required: tier.required, dataFlows: tier.dataFlow, candidates: t.assignee.members.map((m) => this.state(m)),
      linkMetrics: this.linksFor(r), initiatorId: r.id, kMax: t.assignee.members.length,
    })
    return res.success && res.coalition?.members.length === t.assignee.members.length
  }

  private flowsFeasible(r: Replica, t: RTask): boolean {
    if (t.assignee === null || typeof t.assignee === 'string') return true
    const tier = t.def.tiers[t.currentTier]
    if (!tier) return true
    const links = this.linksFor(r)
    return tier.dataFlow.every((f) => {
      const src = (t.assignee as Coalition).roleAssignment[f.sourceCapability]
      const sink = (t.assignee as Coalition).roleAssignment[f.sinkCapability]
      if (!src || !sink || src === sink) return true
      return links.getBandwidth(src, sink) >= f.bandwidthKbps && (f.maxLatencyMs === undefined || links.getLatency(src, sink) <= f.maxLatencyMs)
    })
  }

  // ─── replicas: fork, merge, detect ──────────────────────────────────

  private markDirty(): void {
    if (this.topoDirtySince === null) this.topoDirtySince = this.tick
  }

  private sortedReplicas(): Replica[] {
    return [...this.replicas.values()].sort((a, b) => (a.id < b.id ? -1 : 1))
  }

  private newReplica(ledger?: (id: string) => LocalStateLedger): Replica {
    const id = `R${++this.ids.replica}`
    const now = () => this.tick * TICK_SECONDS
    const r = new Replica(id, ledger ? ledger(id) : new LocalStateLedger(id, now))
    this.replicas.set(id, r)
    return r
  }

  private blankTasks(r: Replica): void {
    for (const def of this.taskDefs) {
      r.tasks.set(def.taskId, { def, currentTier: 0, status: TaskStatus.ABANDONED, assignee: null, progress: 0, matchQuality: 0 })
    }
  }

  /** Bring replica membership in line with the physical radio graph: split, react to losses, merge. */
  private syncTopology(): void {
    const since = this.topoDirtySince ?? this.tick
    this.topoDirtySince = null
    this.responded = true
    const comps = this.components()
    const compOf = new Map<string, number>()
    comps.forEach((c, i) => c.forEach((id) => compOf.set(id, i)))

    // 1. Each replica keeps its largest surviving fragment; other fragments fork the ledger.
    for (const r of this.sortedReplicas()) {
      const pieces = new Map<number, string[]>()
      for (const id of [...r.members].sort()) {
        const c = compOf.get(id)
        if (c === undefined) continue
        pieces.set(c, [...(pieces.get(c) ?? []), id])
      }
      const before = [...r.members]
      if (pieces.size === 0) {
        this.replicas.delete(r.id)
        continue
      }
      const ordered = [...pieces.values()].sort((a, b) => b.length - a.length || ((a[0] as string) < (b[0] as string) ? -1 : 1))
      const forks: Replica[] = []
      ordered.slice(1).forEach((piece) => {
        const f = this.newReplica((id) => r.ledger.fork(id))
        for (const t of r.tasks.values()) f.tasks.set(t.def.taskId, { ...t, assignee: structuredClone(t.assignee) })
        f.members = new Set(piece)
        piece.forEach((id) => ((this.nodes.get(id) as SimNode).replicaId = f.id))
        forks.push(f)
      })
      r.members = new Set(ordered[0])
      if (forks.length > 0) {
        this.log('PARTITION', 'crit', 'harness', `Replica ${r.id} split into ${forks.length + 1} partitions`, {
          replicaId: r.id, nodeIds: before,
          detail: [r, ...forks].map((x) => `${x.id}: ${[...x.members].join(', ')}`).join('  |  '),
        })
      }
      for (const x of [r, ...forks]) {
        const departed = before.filter((id) => !x.members.has(id)).sort()
        for (const id of departed) x.ledger.writeLocal(`node.${id}.status`, 'UNREACHABLE', 'RESOURCE')
        if (departed.length > 0) {
          this.log('DETECT', 'warn', 'harness', `${x.id} lost contact with ${departed.length} node${departed.length > 1 ? 's' : ''}`, {
            replicaId: x.id, nodeIds: departed, detail: `${departed.join(', ')} — ${DETECT_TICKS} beacons missed`,
          })
        }
        this.checkAssignments(x, departed.length)
      }
    }

    // 2. Nodes with no replica yet (boot, join, recovery) start a fresh ledger per component.
    comps.forEach((c) => {
      const fresh = c.filter((id) => (this.nodes.get(id) as SimNode).replicaId === null)
      if (fresh.length === 0) return
      const r = this.newReplica()
      this.blankTasks(r)
      r.members = new Set(fresh)
      r.needsReplan = true
      fresh.forEach((id) => {
        ;(this.nodes.get(id) as SimNode).replicaId = r.id
        r.ledger.writeLocal(`node.${id}.status`, 'ACTIVE', 'RESOURCE')
      })
    })

    // 3. Replicas that now share a component reconcile into the largest one.
    comps.forEach((c) => {
      const present = [...new Set(c.map((id) => (this.nodes.get(id) as SimNode).replicaId as string))]
        .map((id) => this.replicas.get(id) as Replica)
        .sort((a, b) => b.members.size - a.members.size || (a.id < b.id ? -1 : 1))
      const survivor = present[0]
      if (!survivor) return
      for (const other of present.slice(1)) {
        this.reconcile(survivor, other, this.tick - since)
        survivor.needsReplan = true
      }
      if (present.length > 1) this.checkAssignments(survivor, 2)
    })

    // 4. Replicas that gained resources try to restart and upgrade work.
    for (const r of this.sortedReplicas()) {
      if (r.needsReplan) {
        r.needsReplan = false
        this.replan(r, 'resources gained')
      }
    }
  }

  private reconcile(a: Replica, b: Replica, ticksSinceChange: number): void {
    const t0 = performance.now()
    for (const r of [a, b]) for (const id of [...r.members].sort()) r.ledger.writeLocal(`node.${id}.status`, 'ACTIVE', 'RESOURCE')
    const toA = getUnseenEvents(b.ledger.eventLog, a.ledger.versionVector)
    const toB = getUnseenEvents(a.ledger.eventLog, b.ledger.versionVector)

    // The absorbed side runs the same algorithm on a copy, so convergence can be checked rather than assumed.
    const shadow = b.ledger.fork(b.id)
    const reverse = handleReconnection(shadow, a.id, a.ledger.lamportClock, a.ledger.versionVector, toB)
    const effects: SideEffect[] = []
    const forward = handleReconnection(a.ledger, b.id, b.ledger.lamportClock, b.ledger.versionVector, toA, (e) => effects.push(e))

    // Keys known to only one side are transferred with the kernel's write_received (it accepts unknown keys).
    let transferred = 0
    const transfer = (from: LocalStateLedger, to: LocalStateLedger) => {
      for (const [key, e] of [...from.entries].sort((x, y) => (x[0] < y[0] ? -1 : 1))) {
        if (to.entries.has(key)) continue
        to.writeReceived({
          key, value: structuredClone(e.value), semanticType: e.semanticType, sourceNode: e.sourceNode, sourceClock: e.lamportClock,
          sourceWallTime: e.wallTime, confidence: e.confidence, provenance: { ...e.provenance },
        })
        transferred += 1
      }
    }
    transfer(shadow, a.ledger)
    transfer(a.ledger, shadow)

    const diverged: string[] = []
    for (const [key, e] of a.ledger.entries) {
      const o = shadow.entries.get(key)
      if (o && e.semanticType !== 'OBSERVATIONAL' && !valuesEqual(e.value, o.value)) diverged.push(key)
    }
    diverged.sort()
    const wallMs = performance.now() - t0

    const conflicts: ConflictView[] = forward.resolutionDetails.map((c) => ({
      key: c.key, type: c.semanticType, local: digest(c.localEntry.value), remote: digest(c.remoteEntry.value),
      strategy: c.resolution?.strategy ?? '—', winner: c.resolution?.winningSource ?? '—', reason: c.resolution?.reason ?? '',
      sideEffects: (c.resolution?.sideEffects ?? []).filter((e) => e.target).map((e) => `${e.type} → ${e.target}`),
    }))
    const absorbedMembers = [...b.members].sort()
    const rec: ReconciliationRecord = {
      id: ++this.ids.recon, tick: this.tick, survivor: a.id, absorbed: b.id, survivorMembers: [...a.members].sort(), absorbedMembers,
      eventsToSurvivor: toA.length, eventsToAbsorbed: toB.length, mergedForward: forward.entriesMerged, mergedReverse: reverse.entriesMerged,
      conflicts, transferred, divergedKeys: diverged, converged: diverged.length === 0, ticksSinceChange, wallMs,
    }
    this.reconciliations.push(rec)
    this.msg.reconcile += toA.length + toB.length + transferred

    this.log('RECONCILE', diverged.length ? 'warn' : 'ok', 'kernel', `${b.id} reconciled into ${a.id}: ${conflicts.length} conflict${conflicts.length === 1 ? '' : 's'}`, {
      replicaId: a.id, algo: '008', nodeIds: absorbedMembers,
      detail: `${toA.length + toB.length} events exchanged · ${forward.entriesMerged} entries merged · ` +
        (diverged.length ? `${diverged.length} key(s) differ between the two sides after the merge` : 'both sides reach the same state'),
    })
    for (const c of conflicts.filter((x) => x.type === 'EXCLUSIVE_OWNERSHIP')) {
      this.log('CONFLICT', 'warn', 'kernel', `${c.key}: dual ownership resolved`, {
        replicaId: a.id, algo: '008', taskId: c.key.replace('task_owner.', ''), detail: `${c.reason} — ${c.winner} side wins`,
      })
    }
    const other = conflicts.filter((x) => x.type !== 'EXCLUSIVE_OWNERSHIP').length
    if (other > 0) {
      this.log('CONFLICT', 'info', 'kernel', `${other} node-status observation${other === 1 ? '' : 's'} resolved by recency`, { replicaId: a.id, algo: '008' })
    }

    // The survivor's merged ledger becomes the component's state.
    for (const id of absorbedMembers) {
      a.members.add(id)
      ;(this.nodes.get(id) as SimNode).replicaId = a.id
    }
    this.replicas.delete(b.id)
    for (const t of a.tasks.values()) {
      const v = a.ledger.entries.get(ownerKey(t.def.taskId))?.value as OwnerValue | undefined
      if (!v) continue
      t.currentTier = v.tier
      t.status = v.status
      t.progress = v.progress
      t.matchQuality = v.match_quality
      t.assignee = v.coalition ? structuredClone(v.coalition) : v.assignee || null
    }
  }

  /** Find tasks whose assignees are gone (or double-booked after a merge) and let the kernel respond. */
  private checkAssignments(r: Replica, departedCount: number): void {
    const claimed = new Set<string>()
    const affected: RTask[] = []
    let source: string | null = null
    for (const t of r.byPriority()) {
      if (!isActive(t)) continue
      const ms = membersOf(t)
      const bad = ms.filter((m) => !r.members.has(m) || claimed.has(m))
      if (bad.length > 0) {
        affected.push(t)
        source ??= bad[0] as string
      } else {
        ms.forEach((m) => claimed.add(m))
      }
    }
    if (affected.length === 0 || source === null) return
    this.runTrigger(r, { triggerType: departedCount === 1 ? 'NODE_LOSS' : 'LINK_LOSS', sourceNode: source }, affected)
  }

  private onEnergyCritical(n: SimNode): void {
    n.depleted = true
    this.log('FAULT', 'warn', 'harness', `${n.id} energy critical (${Math.round(n.energy * 100)}%)`, {
      nodeIds: [n.id], detail: 'Node withdraws from mission work but keeps relaying.',
    })
    const r = n.replicaId ? this.replicas.get(n.replicaId) : undefined
    if (!r) return
    const affected = [...r.tasks.values()].filter((t) => isActive(t) && membersOf(t).includes(n.id))
    if (affected.length > 0) this.runTrigger(r, { triggerType: 'ENERGY_CRITICAL', sourceNode: n.id }, affected)
  }

  // ─── kernel invocations ─────────────────────────────────────────────

  private runTrigger(r: Replica, trigger: DegradationTrigger, affected: RTask[]): void {
    r.affected = affected
    const busy = new Set<string>()
    for (const t of r.tasks.values()) if (isActive(t) && !affected.includes(t)) membersOf(t).forEach((m) => busy.add(m))
    const known = this.usable(r).filter((id) => !busy.has(id)).map((id) => this.state(id))
    const plan = handleDegradationTrigger(trigger, r, known, this.ctx(r))
    r.affected = []
    if (plan) this.applyPlan(r, plan)
  }

  private applyPlan(r: Replica, plan: DegradationPlan): void {
    this.msg.coordination += r.members.size
    const seenUpgrade = new Set<string>()
    for (const e of plan.decisionTrace) {
      if (e.action === 'UPGRADE') {
        if (seenUpgrade.has(e.taskId)) continue
        seenUpgrade.add(e.taskId)
      }
      const def = taskById(e.taskId)
      const who = e.newAssignee === null ? [] : typeof e.newAssignee === 'string' ? [e.newAssignee] : e.newAssignee.members
      const coalition = e.newAssignee !== null && typeof e.newAssignee !== 'string'
      const kind: EventKind = e.action === 'DEGRADE' && coalition && e.newTier === e.oldTier ? 'COALITION' : e.action
      const sev: Severity = e.action === 'ALARM' || e.action === 'ABANDON' ? 'crit' : e.action === 'UPGRADE' ? 'ok' : e.newTier !== null && e.oldTier !== null && e.newTier > e.oldTier ? 'warn' : 'info'
      const title =
        e.action === 'REASSIGN' ? `${def.code}: role inherited by ${who[0]} at tier ${e.newTier}`
        : e.action === 'DEGRADE' ? `${def.code}: coalition ${who.join(' + ')} at tier ${e.newTier}`
        : e.action === 'ABANDON' ? `${def.code}: abandoned — no tier satisfiable`
        : e.action === 'UPGRADE' ? `${def.code}: upgraded to tier ${e.newTier}`
        : `${def.code}: CRITICAL task abandoned`
      this.log(kind, sev, 'kernel', title, {
        replicaId: r.id, taskId: e.taskId, nodeIds: who, algo: '006',
        detail: e.qualityChange ? `${plan.trigger.triggerType} · quality ${e.qualityChange[0].toFixed(2)} → ${e.qualityChange[1].toFixed(2)}` : e.reason,
      })
    }
    for (const id of plan.abandonedTasks) {
      const t = r.tasks.get(id)
      if (t && !(id in plan.newAssignments)) this.setAbandoned(r, t)
    }
    for (const [id, assignee] of Object.entries(plan.newAssignments)) {
      const t = r.tasks.get(id)
      const ch = plan.tierChanges[id]
      if (t && ch) this.setAssignment(r, t, ch[1], assignee)
    }
  }

  private setAssignment(r: Replica, t: RTask, tier: number, assignee: string | Coalition): void {
    const def = t.def.tiers[tier]
    t.currentTier = tier
    t.status = tier === 0 ? TaskStatus.EXECUTING : TaskStatus.DEGRADED
    t.progress = 0
    if (typeof assignee === 'string') {
      t.assignee = assignee
      t.matchQuality = def ? round4(computeFullMatch(this.state(assignee), def.required, def.preferred).quality) : 0
    } else {
      t.assignee = { ...assignee, status: 'ACTIVE' }
      const qs = assignee.members.map((m) => (def ? computeMatchQuality(this.state(m), def.preferred) : 0))
      t.matchQuality = round4(qs.reduce((s, q) => s + q, 0) / Math.max(1, qs.length))
    }
    this.recordOwner(r, t)
  }

  private setAbandoned(r: Replica, t: RTask): void {
    t.status = TaskStatus.ABANDONED
    t.assignee = null
    t.currentTier = 0
    t.progress = 0
    t.matchQuality = 0
    this.recordOwner(r, t)
  }

  private recordOwner(r: Replica, t: RTask): void {
    const ms = membersOf(t)
    const value: OwnerValue = {
      assignee: ms.join('+'), members: ms, tier: t.currentTier, status: t.status, progress: t.progress, match_quality: t.matchQuality,
      coalition: t.assignee !== null && typeof t.assignee !== 'string' ? structuredClone(t.assignee) : null,
    }
    r.ledger.writeLocal(ownerKey(t.def.taskId), value, 'EXCLUSIVE_OWNERSHIP')
  }

  /**
   * Harness policy for newly available resources: auction unowned tasks
   * (Algorithms 003–005), then run the kernel's upgrade pass (006).
   */
  private replan(r: Replica, why: string): void {
    for (const t of r.byPriority()) if (t.status === TaskStatus.ABANDONED) this.allocate(r, t)
    // One pass per degraded task, so a task's own nodes count as available for its upgrade
    // (the kernel's attempt_upgrades only ever looks at nodes handed to it as free).
    for (const t of r.byPriority()) {
      if (!isActive(t) || t.currentTier === 0) continue
      const own = membersOf(t).filter((m) => this.usable(r).includes(m)).map((m) => this.state(m))
      const up = attemptUpgrades([t], new AvailableNodes([...this.freeStates(r), ...own]), this.ctx(r))[0]
      if (!up) continue
      const [, tier, assignee] = up
      const from = t.currentTier
      this.setAssignment(r, t, tier, assignee)
      const who = typeof assignee === 'string' ? [assignee] : assignee.members
      this.log('UPGRADE', 'ok', 'kernel', `${t.def.code}: upgraded tier ${from} → ${tier} (${who.join(' + ')})`, {
        replicaId: r.id, taskId: t.def.taskId, nodeIds: who, algo: '006', detail: `Upgrade pass after ${why}`,
      })
    }
  }

  /** Auction one task inside a replica: bids at each tier, coalition if nobody can do it alone. */
  private allocate(r: Replica, t: RTask): void {
    const swarm = this.usable(r).map((id) => this.state(id))
    for (let i = 0; i < t.def.tiers.length; i++) {
      const tier = t.def.tiers[i]
      if (!tier || tier.qualityEstimate < t.def.qMin) continue
      const free = this.freeStates(r)
      const bids: Bid[] = []
      const ineligible: AuctionRound['ineligible'] = []
      for (const s of free) {
        const m = computeFullMatch(s, tier.required, tier.preferred)
        if (!m.eligible) {
          ineligible.push({ nodeId: s.nodeId, unmet: [...m.unmetRequired].sort() })
          continue
        }
        const energy = (this.nodes.get(s.nodeId) as SimNode).energy
        const penalty = computeScarcityPenalty(s, new Set(Object.keys(tier.required)), swarm)
        bids.push({
          taskId: t.def.taskId, nodeId: s.nodeId, matchQuality: m.weightedQuality, energy, scarcityPenalty: penalty,
          systemCost: computeSystemCost(m.weightedQuality, energy, BASE_CONSUMPTION, penalty),
        })
      }
      const result = evaluateBids(bids, t.def.taskId)
      const roundRec: AuctionRound = {
        id: ++this.ids.auction, tick: this.tick, replicaId: r.id, taskId: t.def.taskId, tier: i, participants: free.length,
        bids: bids.map((b) => ({ nodeId: b.nodeId, cost: b.systemCost, quality: b.matchQuality, energy: b.energy, scarcityPenalty: b.scarcityPenalty }))
          .sort((a, b) => a.cost - b.cost),
        ineligible, outcome: 'UNFILLED', winner: null, runnerUp: result.runnerUpNode, coalition: null, coalitionNote: null,
      }
      this.auctions.push(roundRec)
      if (this.auctions.length > MAX_AUCTIONS) this.auctions.shift()
      this.msg.coordination += r.members.size + bids.length + 1

      if (result.assignedNode) {
        roundRec.outcome = 'SOLO'
        roundRec.winner = result.assignedNode
        this.setAssignment(r, t, i, result.assignedNode)
        this.log('AUCTION', i === 0 ? 'info' : 'warn', 'kernel', `${t.def.code}: awarded to ${result.assignedNode} at tier ${i}`, {
          replicaId: r.id, taskId: t.def.taskId, nodeIds: [result.assignedNode], algo: '004',
          detail: `${bids.length} bid${bids.length === 1 ? '' : 's'} · cost ${(result.systemCost ?? 0).toFixed(3)}` +
            (result.runnerUpNode ? ` · runner-up ${result.runnerUpNode} at ${(result.runnerUpCost ?? 0).toFixed(3)}` : ''),
        })
        return
      }
      const co = formCoalition({
        taskId: t.def.taskId, required: tier.required, dataFlows: tier.dataFlow, candidates: free, linkMetrics: this.linksFor(r),
        initiatorId: r.id, coalitionId: `coal-${++this.ids.coalition}`, now: this.tick * TICK_SECONDS,
      })
      this.msg.coordination += co.candidatesTried * 2
      if (co.success && co.coalition) {
        roundRec.outcome = 'COALITION'
        roundRec.coalition = co.coalition.members
        this.setAssignment(r, t, i, co.coalition)
        this.log('COALITION', i === 0 ? 'info' : 'warn', 'kernel', `${t.def.code}: coalition ${co.coalition.members.join(' + ')} at tier ${i}`, {
          replicaId: r.id, taskId: t.def.taskId, nodeIds: co.coalition.members, algo: '005',
          detail: `No single node eligible · estimated cost ${co.coalition.estimatedCost.toFixed(2)}`,
        })
        return
      }
      roundRec.coalitionNote = co.rejectionReason ?? null
    }
    if (t.assignee !== null || !r.ledger.entries.has(ownerKey(t.def.taskId))) {
      this.setAbandoned(r, t)
      this.log('ABANDON', t.def.priorityClass === 'CRITICAL' ? 'crit' : 'warn', 'kernel', `${t.def.code}: no bidder or coalition at any tier`, {
        replicaId: r.id, taskId: t.def.taskId, algo: '004',
      })
    }
  }

  // ─── records ────────────────────────────────────────────────────────

  private log(kind: EventKind, severity: Severity, source: Source, title: string, extra: Partial<SimEvent> = {}): void {
    this.events.push({ id: ++this.ids.event, tick: this.tick, kind, severity, source, title, nodeIds: [], ...extra })
    if (this.events.length > MAX_EVENTS) this.events.shift()
  }

  private openFault(kind: FaultKind, label: string, nodeIds: string[]): void {
    this.faults.push({ id: ++this.ids.fault, tick: this.tick, kind, label, nodeIds, utilityBefore: this.effectiveUtility().utility, respondedTick: null, utilityAfter: null })
  }

  private settleFaults(): void {
    if (!this.responded) return
    this.responded = false
    const u = this.effectiveUtility().utility
    for (const f of this.faults) {
      if (f.respondedTick === null) {
        f.respondedTick = this.tick
        f.utilityAfter = u
      }
    }
  }

  private replaceLastSample(): void {
    const last = this.metrics[this.metrics.length - 1]
    if (last && last.tick === this.tick) this.metrics[this.metrics.length - 1] = this.sample()
    else this.metrics.push(this.sample())
  }

  /** Mission utility that is physically being delivered, counting each task once across partitions. */
  private effectiveUtility(): { utility: number; duplicated: number; full: number; degraded: number; abandoned: number } {
    const comp = this.componentIndex()
    let utility = 0
    let duplicated = 0
    let full = 0
    let degraded = 0
    for (const def of this.taskDefs) {
      let best = 0
      let count = 0
      for (const r of this.replicas.values()) {
        const t = r.tasks.get(def.taskId)
        if (t && this.isLive(t, comp)) {
          count += 1
          best = Math.max(best, currentQuality(t))
        }
      }
      utility += def.missionPriority * best
      if (count > 1) duplicated += 1
      if (best >= 1) full += 1
      else if (best > 0) degraded += 1
    }
    return { utility, duplicated, full, degraded, abandoned: this.taskDefs.length - full - degraded }
  }

  private agreement(): number {
    const rs = this.sortedReplicas()
    if (rs.length <= 1 || this.taskDefs.length === 0) return 1
    let agreed = 0
    for (const def of this.taskDefs) {
      const views = rs.map((r) => {
        const t = r.tasks.get(def.taskId)
        return t ? `${membersOf(t).join('+')}@${t.currentTier}:${t.status}` : ''
      })
      if (views.every((v) => v === views[0])) agreed += 1
    }
    return agreed / this.taskDefs.length
  }

  private sample(): MetricSample {
    const present = [...this.nodes.values()].filter((n) => !n.removed)
    const live = present.filter((n) => n.alive)
    const comps = this.components()
    const pairs = (n: number) => (n * (n - 1)) / 2
    const eu = this.effectiveUtility()
    const maxUtility = this.taskDefs.reduce((s, d) => s + d.missionPriority, 0)
    const busy = live.filter((n) => this.roleOf(n) !== null).length
    const coordination = this.msg.coordination
    return {
      tick: this.tick, utility: round4(eu.utility), maxUtility: round4(maxUtility), utilityRatio: maxUtility ? round4(eu.utility / maxUtility) : 0,
      activeNodes: live.length, failedNodes: present.length - live.length, components: comps.length,
      connectivity: live.length > 1 ? round4(comps.reduce((s, c) => s + pairs(c.length), 0) / pairs(live.length)) : 1,
      links: this.upLinkCount(), messages: this.msg.beacon + coordination + this.msg.reconcile, msgBeacon: this.msg.beacon,
      msgCoordination: coordination, msgReconcile: this.msg.reconcile,
      busyRatio: live.length ? round4(busy / live.length) : 0,
      meanEnergy: live.length ? round4(live.reduce((s, n) => s + n.energy, 0) / live.length) : 0,
      duplicated: eu.duplicated, agreement: round4(this.agreement()),
      tasksFull: eu.full, tasksDegraded: eu.degraded, tasksAbandoned: eu.abandoned, latencyFactor: this.latencyFactor,
    }
  }

  private build(): WorldSnapshot {
    const comp = this.componentIndex()
    const present = [...this.nodes.values()].filter((n) => !n.removed)
    const links: LinkView[] = []
    for (let i = 0; i < present.length; i++) {
      for (let j = i + 1; j < present.length; j++) {
        const a = present[i] as SimNode
        const b = present[j] as SimNode
        const d = distance(a, b)
        if (!a.alive || !b.alive || d > COMM_RANGE) continue
        links.push({ a: a.id, b: b.id, distance: d, bandwidthKbps: linkBandwidth(d), latencyMs: linkLatency(d) * this.latencyFactor, up: !this.jammed(a, b) })
      }
    }
    const nodes: NodeView[] = present.map((n) => {
      const t = this.roleOf(n)
      const degraded = Object.keys(n.baseDims).some((d) => n.dims[d] !== n.baseDims[d])
      const health: Health = !n.alive ? 'FAILED' : n.depleted ? 'DEPLETED' : degraded ? 'DEGRADED' : 'NOMINAL'
      const co = t && t.assignee !== null && typeof t.assignee !== 'string' ? t.assignee : null
      return {
        id: n.id, archetype: n.archetype, x: n.x, y: n.y, alive: n.alive, depleted: n.depleted, isolated: this.isolated.has(n.id), health,
        energy: n.energy, dims: n.dims, baseDims: n.baseDims, replicaId: n.replicaId, joinedTick: n.joinedTick,
        role: t ? {
          taskId: t.def.taskId, tier: t.currentTier, kind: co ? 'COALITION' : 'SOLO',
          provides: co ? Object.entries(co.roleAssignment).filter(([, p]) => p === n.id).map(([d]) => d) : Object.keys(t.def.tiers[t.currentTier]?.required ?? {}),
        } : null,
        neighbours: links.filter((l) => l.up && (l.a === n.id || l.b === n.id)).map((l) => (l.a === n.id ? l.b : l.a)),
      }
    })
    const replicas: ReplicaView[] = this.sortedReplicas().map((r) => {
      const tasks: TaskView[] = this.taskDefs.map((def) => {
        const t = r.tasks.get(def.taskId) as RTask
        const co = t.assignee !== null && typeof t.assignee !== 'string' ? t.assignee : null
        return {
          taskId: def.taskId, code: def.code ?? def.taskId, name: def.name ?? def.taskId, priorityClass: def.priorityClass,
          missionPriority: def.missionPriority, tierCount: def.tiers.length, tier: t.currentTier,
          tierLabel: def.tiers[t.currentTier]?.label ?? '', status: t.status,
          kind: co ? 'COALITION' : t.assignee ? 'SOLO' : 'NONE', members: membersOf(t), roles: co ? co.roleAssignment : {},
          flows: co ? co.dataFlowPlan : [], quality: currentQuality(t), progress: t.progress, matchQuality: t.matchQuality, live: this.isLive(t, comp),
        }
      })
      const ledger: LedgerRow[] = [...r.ledger.entries.values()].sort((a, b) => (a.key < b.key ? -1 : 1)).map((e) => ({
        key: e.key, type: e.semanticType, digest: digest(e.value), source: e.sourceNode, clock: e.lamportClock, conflict: e.conflict !== null,
      }))
      return {
        id: r.id, members: [...r.members].sort(), lamport: r.ledger.lamportClock, seq: r.ledger.seqNum, versionVector: { ...r.ledger.versionVector },
        eventCount: r.ledger.eventLog.length, utility: round4(computeSwarmUtility([...r.tasks.values()])), tasks, ledger,
      }
    })
    return {
      tick: this.tick, timeS: this.tick * TICK_SECONDS, seed: this.seed, preset: this.preset, tickSeconds: TICK_SECONDS, detectTicks: DETECT_TICKS,
      latencyFactor: this.latencyFactor, cut: this.cut,
      pendingDetection: this.topoDirtySince === null ? null : Math.max(0, DETECT_TICKS - (this.tick - this.topoDirtySince)),
      nodes, links, replicas, taskIds: this.taskDefs.map((d) => d.taskId),
      events: [...this.events], metrics: [...this.metrics], auctions: [...this.auctions],
      reconciliations: [...this.reconciliations], faults: this.faults.map((f) => ({ ...f })),
    }
  }
}

interface OwnerValue {
  assignee: string
  members: string[]
  tier: number
  status: RTask['status']
  progress: number
  match_quality: number
  coalition: Coalition | null
}

/** Short human-readable rendering of a ledger value. */
export function digest(v: unknown): string {
  if (Array.isArray(v)) return `{${v.length} item${v.length === 1 ? '' : 's'}}`
  if (v && typeof v === 'object') {
    const o = v as Partial<OwnerValue>
    if (o.status === TaskStatus.ABANDONED) return 'unowned'
    if (typeof o.assignee === 'string') return `${o.assignee || '—'} · T${o.tier ?? 0} · ${Math.round((o.progress ?? 0) * 100)}%`
    return JSON.stringify(v)
  }
  return String(v)
}
