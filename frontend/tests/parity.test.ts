/**
 * Parity between the TypeScript port and the reference Python kernel.
 * Expected values in fixtures/parity.json come from running the real `hesk`
 * package (scripts/gen_parity_fixtures.py) over the same catalog.
 */
import { describe, expect, it } from 'vitest'
import fx from './fixtures/parity.json'
import { computeScarcityPenalty, computeSystemCost, evaluateBids, type Bid } from '../src/kernel/allocation'
import { formCoalition, type Coalition } from '../src/kernel/coalition'
import { handleDegradationTrigger, type ActiveTask, type DegradationLedger } from '../src/kernel/degradation'
import { LocalStateLedger, type StateSemanticType } from '../src/kernel/ledger'
import { computeFullMatch } from '../src/kernel/matching'
import { getUnseenEvents, handleReconnection, type SideEffect } from '../src/kernel/reconciliation'
import { TaskStatus, type CapabilityState } from '../src/kernel/types'
import { buildPresetNodes, geometricLinks, taskById, TASKS, toState } from '../src/sim/catalog'

const seeds = buildPresetNodes('baseline')
const nodes: CapabilityState[] = seeds.map((n) => toState(n))
const byId = new Map(nodes.map((n) => [n.nodeId, n]))
const energy = new Map(seeds.map((n, i) => [n.id, Math.round((1 - 0.03 * i) * 1e4) / 1e4]))
const links = geometricLinks(Object.fromEntries(seeds.map((n) => [n.id, n])))
const tierOf = (task: string, tier: number) => taskById(task).tiers[tier]!
const outAssignee = (a: string | Coalition) =>
  typeof a === 'string' ? a : { members: a.members, roles: a.roleAssignment, cost: a.estimatedCost }
let cid = 0
const ctx = { linkMetrics: links, now: 0, nextCoalitionId: () => `c${cid++}` }

describe('kernel parity with the Python reference', () => {
  it('003 capability matching', () => {
    expect(fx.match.length).toBeGreaterThan(100)
    for (const c of fx.match) {
      const t = tierOf(c.task, c.tier)
      const m = computeFullMatch(byId.get(c.node)!, t.required, t.preferred)
      expect(m.eligible, `${c.task}/${c.tier}/${c.node}`).toBe(c.eligible)
      expect(m.quality).toBeCloseTo(c.quality, 12)
      expect([...m.unmetRequired].sort()).toEqual(c.unmet)
    }
  })

  it('004 scarcity-aware allocation', () => {
    for (const c of fx.allocation) {
      const t = tierOf(c.task, c.tier)
      const bids: Bid[] = []
      for (const n of nodes) {
        const m = computeFullMatch(n, t.required, t.preferred)
        if (!m.eligible) continue
        const e = energy.get(n.nodeId)!
        const pen = computeScarcityPenalty(n, new Set(Object.keys(t.required)), nodes)
        bids.push({ taskId: c.task, nodeId: n.nodeId, systemCost: computeSystemCost(m.weightedQuality, e, 0.1, pen), matchQuality: m.weightedQuality, energy: e, scarcityPenalty: pen })
      }
      const expected = c.bids as unknown as Record<string, number>
      expect(bids.map((b) => b.nodeId).sort()).toEqual(Object.keys(expected).sort())
      for (const b of bids) expect(b.systemCost).toBeCloseTo(expected[b.nodeId]!, 10)
      const r = evaluateBids(bids, c.task)
      expect(r.assignedNode).toBe(c.winner)
      expect(r.runnerUpNode).toBe(c.runnerUp)
    }
  })

  it('005 coalition formation', () => {
    for (const c of fx.coalition) {
      const t = tierOf(c.task, c.tier)
      const candidates = c.candidates === 'all' ? nodes : nodes.filter((n) => !n.nodeId.startsWith('ISR'))
      const r = formCoalition({ taskId: c.task, required: t.required, dataFlows: t.dataFlow, candidates, linkMetrics: links, initiatorId: 'init' })
      expect(r.success, `${c.task}/${c.tier}/${c.candidates}`).toBe(c.success)
      if (c.success && c.result && r.coalition) {
        const exp = c.result as unknown as { members: string[]; roles: Record<string, string>; cost: number }
        expect(r.coalition.members).toEqual(exp.members)
        expect(r.coalition.roleAssignment).toEqual(exp.roles)
        expect(r.coalition.estimatedCost).toBeCloseTo(exp.cost, 10)
      }
    }
  })

  it('006 graceful degradation', () => {
    const initial = fx.initial as unknown as Record<string, string>
    for (const c of fx.degradation) {
      const tasks: ActiveTask[] = TASKS.map((def) => initial[def.taskId]
        ? { def, currentTier: 0, status: TaskStatus.EXECUTING, assignee: initial[def.taskId]! }
        : { def, currentTier: 0, status: TaskStatus.ABANDONED, assignee: null })
      const ledger: DegradationLedger = {
        getAffectedTasks: (tr) => tasks.filter((t) => t.assignee === tr.sourceNode),
        getAllActiveTasks: () => tasks,
        releaseTaskResources: (t) => (typeof t.assignee === 'string' ? [t.assignee] : []),
      }
      const plan = handleDegradationTrigger({ triggerType: 'NODE_LOSS', sourceNode: c.lost }, ledger, c.known.map((id) => byId.get(id)!), ctx)!
      expect(plan.tierChanges, c.lost).toEqual(c.tierChanges)
      const got = Object.fromEntries(Object.entries(plan.newAssignments).map(([k, v]) => [k, outAssignee(v)]))
      expect(JSON.parse(JSON.stringify(got))).toEqual(c.assignments)
      expect(plan.abandonedTasks).toEqual(c.abandoned)
      expect(plan.utilityBefore).toBeCloseTo(c.utilityBefore, 10)
      expect(plan.utilityAfter).toBeCloseTo(c.utilityAfter, 10)
      expect(plan.decisionTrace.map((e) => [e.taskId, e.action])).toEqual(c.trace)
    }
  })

  it('007/008 ledger merge and partition reconciliation', () => {
    const r = fx.reconciliation
    let now = 0
    const led: Record<string, LocalStateLedger> = { a: new LocalStateLedger('a', () => now), b: new LocalStateLedger('b', () => now) }
    for (const op of r.ops as Array<[string, number, string, unknown, StateSemanticType]>) {
      now = op[1]
      led[op[0]]!.writeLocal(op[2], op[3], op[4])
    }
    now = r.at
    const effects: SideEffect[] = []
    const a = led.a!
    const b = led.b!
    const trace = handleReconnection(a, 'b', b.lamportClock, b.versionVector, getUnseenEvents(b.eventLog, a.versionVector), (e) => effects.push(e))
    expect(trace.conflictsFound).toBe(r.conflictsFound)
    expect(trace.entriesMerged).toBe(r.entriesMerged)
    const res = Object.fromEntries(trace.resolutionDetails.map((c) => [c.key, { strategy: c.resolution!.strategy, winner: c.resolution!.winningSource }]))
    const expRes = Object.fromEntries(Object.entries(r.resolutions).map(([k, v]) => [k, { strategy: v.strategy, winner: v.winner }]))
    expect(res).toEqual(expRes)
    expect(effects.map((e) => [e.type, e.target, e.task]).sort()).toEqual(r.sideEffects)
    expect(Object.fromEntries([...a.entries].sort().map(([k, e]) => [k, e.value]))).toEqual(r.entries)
    expect(a.lamportClock).toBe(r.lamport)
    // Documented kernel gap: an update made only on the remote side is not merged.
    expect(a.entries.has('task_owner.remote_only')).toBe(false)
  })
})
