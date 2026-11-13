/**
 * Port of src/hesk/degradation/logic.py — Algorithm 006, graceful degradation.
 * Ported faithfully, including behaviours the laboratory surfaces as findings
 * (reassignment ignores energy/scarcity; the upgrade cascade does not mutate
 * task state between rounds, so one task can be "upgraded" more than once).
 */
import { computeSystemCost } from './allocation'
import { formCoalition, type Coalition } from './coalition'
import { checkEligibility, computeMatchQuality } from './matching'
import { TaskStatus, type CapabilityState, type LinkMetrics, type NodeId, type PriorityClass, type TaskDefinition, type TaskStatusT } from './types'

export const DEGRADATION_CASCADE_LIMIT = 3

export type DegradationTriggerType = 'NODE_LOSS' | 'CAPABILITY_DEGRADATION' | 'LINK_LOSS' | 'ENERGY_CRITICAL' | 'COALITION_MEMBER_LOST'
export type TraceAction = 'REASSIGN' | 'DEGRADE' | 'ABANDON' | 'UPGRADE' | 'ALARM'
export type Assignee = NodeId | Coalition | null

export interface DegradationTrigger {
  triggerType: DegradationTriggerType
  sourceNode: NodeId
}

export interface ActiveTask {
  def: TaskDefinition
  currentTier: number
  status: TaskStatusT
  assignee: Assignee
}

export interface TraceEntry {
  taskId: string
  action: TraceAction
  reason: string
  oldTier: number | null
  newTier: number | null
  oldAssignee: Assignee
  newAssignee: Assignee
  qualityChange: [number, number] | null
}

export interface DegradationPlan {
  trigger: DegradationTrigger
  affectedTasks: string[]
  tierChanges: Record<string, [number, number]>
  newAssignments: Record<string, NodeId | Coalition>
  abandonedTasks: string[]
  utilityBefore: number
  utilityAfter: number
  decisionTrace: TraceEntry[]
}

/** The interface the kernel expects from a node's local ledger (LocalLedger in Python). */
export interface DegradationLedger {
  getAffectedTasks(trigger: DegradationTrigger): ActiveTask[]
  getAllActiveTasks(): ActiveTask[]
  releaseTaskResources(task: ActiveTask): NodeId[]
}

export interface DegradationContext {
  linkMetrics: LinkMetrics
  now: number
  nextCoalitionId: () => string
}

const PRIORITY_ORDER: Record<PriorityClass, number> = { CRITICAL: 3, IMPORTANT: 2, OPTIONAL: 1 }
const isActive = (t: ActiveTask) => t.status === TaskStatus.EXECUTING || t.status === TaskStatus.DEGRADED

export const currentQuality = (t: ActiveTask): number =>
  t.status === TaskStatus.ABANDONED ? 0 : (t.def.tiers[t.currentTier]?.qualityEstimate ?? 0)

export class AvailableNodes {
  private nodes = new Map<NodeId, CapabilityState>()
  constructor(known: CapabilityState[], excludeNode?: NodeId) {
    for (const n of known) this.nodes.set(n.nodeId, n)
    if (excludeNode !== undefined) this.nodes.delete(excludeNode)
  }
  getList(): CapabilityState[] {
    return [...this.nodes.values()]
  }
  removeCommitment(id: NodeId): void {
    this.nodes.delete(id)
  }
  addFreed(nodes: CapabilityState[]): void {
    for (const n of nodes) this.nodes.set(n.nodeId, n)
  }
}

/** U_swarm = Σ(π_j × quality_j) over executing or degraded tasks. */
export function computeSwarmUtility(tasks: ActiveTask[]): number {
  return tasks.filter(isActive).reduce((s, t) => s + t.def.missionPriority * currentQuality(t), 0)
}

function utilityWithChanges(tasks: ActiveTask[], tierChanges: Record<string, [number, number]>, abandoned: string[]): number {
  let u = 0
  for (const t of tasks) {
    if (abandoned.includes(t.def.taskId)) continue
    const ch = tierChanges[t.def.taskId]
    if (ch) u += t.def.missionPriority * (t.def.tiers[ch[1]]?.qualityEstimate ?? 0)
    else if (isActive(t)) u += t.def.missionPriority * currentQuality(t)
  }
  return u
}

function bestSolo(eligible: CapabilityState[], preferred: TaskDefinition['tiers'][number]['preferred']): CapabilityState | null {
  let bestCost = Infinity
  let best: CapabilityState | null = null
  for (const n of eligible) {
    // The Python kernel hardcodes energy=1.0, base_consumption=10.0, scarcity_penalty=0.0 here.
    const cost = computeSystemCost(computeMatchQuality(n, preferred), 1.0, 10.0, 0.0)
    if (cost < bestCost) {
      bestCost = cost
      best = n
    }
  }
  return best
}

export type Satisfaction =
  | { action: 'SOLO_REASSIGN'; assignee: NodeId; tier: number }
  | { action: 'COALITION_FORM'; coalition: Coalition; tier: number }
  | { action: 'ABANDON' }

export function findBestSatisfactionWithDescent(task: ActiveTask, available: AvailableNodes, ctx: DegradationContext): Satisfaction {
  const list = available.getList()
  for (let i = task.currentTier; i < task.def.tiers.length; i++) {
    const tier = task.def.tiers[i]
    if (!tier || tier.qualityEstimate < task.def.qMin) continue
    const solo = bestSolo(list.filter((n) => checkEligibility(n, tier.required)), tier.preferred)
    if (solo) return { action: 'SOLO_REASSIGN', assignee: solo.nodeId, tier: i }
    const res = formCoalition({
      taskId: task.def.taskId, required: tier.required, dataFlows: tier.dataFlow, candidates: list,
      linkMetrics: ctx.linkMetrics, initiatorId: 'local_node', coalitionId: ctx.nextCoalitionId(), now: ctx.now,
    })
    if (res.success && res.coalition) return { action: 'COALITION_FORM', coalition: res.coalition, tier: i }
  }
  return { action: 'ABANDON' }
}

export function attemptUpgrades(allTasks: ActiveTask[], available: AvailableNodes, ctx: DegradationContext): Array<[ActiveTask, number, NodeId | Coalition]> {
  const upgrades: Array<[ActiveTask, number, NodeId | Coalition]> = []
  const degraded = allTasks.filter((t) => t.currentTier > 0 && isActive(t))
  degraded.sort((a, b) =>
    PRIORITY_ORDER[b.def.priorityClass] - PRIORITY_ORDER[a.def.priorityClass] || b.def.missionPriority - a.def.missionPriority)
  for (const task of degraded) {
    for (let i = 0; i < task.currentTier; i++) {
      const tier = task.def.tiers[i]
      if (!tier) continue
      const list = available.getList()
      const solo = bestSolo(list.filter((n) => checkEligibility(n, tier.required)), tier.preferred)
      if (solo) {
        upgrades.push([task, i, solo.nodeId])
        available.removeCommitment(solo.nodeId)
        break
      }
      const res = formCoalition({
        taskId: task.def.taskId, required: tier.required, dataFlows: tier.dataFlow, candidates: list,
        linkMetrics: ctx.linkMetrics, initiatorId: 'local_node', coalitionId: ctx.nextCoalitionId(), now: ctx.now,
      })
      if (res.success && res.coalition) {
        upgrades.push([task, i, res.coalition])
        for (const m of res.coalition.members) available.removeCommitment(m)
        break
      }
    }
  }
  return upgrades
}

export function handleDegradationTrigger(
  trigger: DegradationTrigger, ledger: DegradationLedger, knownNodes: CapabilityState[], ctx: DegradationContext,
): DegradationPlan | null {
  const affected = ledger.getAffectedTasks(trigger)
  if (affected.length === 0) return null
  const all = ledger.getAllActiveTasks()
  const utilityBefore = computeSwarmUtility(all)
  affected.sort((a, b) =>
    PRIORITY_ORDER[b.def.priorityClass] - PRIORITY_ORDER[a.def.priorityClass] || b.def.missionPriority - a.def.missionPriority)

  const available = new AvailableNodes(knownNodes, trigger.sourceNode)
  const tierChanges: Record<string, [number, number]> = {}
  const newAssignments: Record<string, NodeId | Coalition> = {}
  const abandoned: string[] = []
  const trace: TraceEntry[] = []
  const q = (t: ActiveTask, tier: number) => t.def.tiers[tier]?.qualityEstimate ?? 0

  for (const task of affected) {
    const id = task.def.taskId
    const r = findBestSatisfactionWithDescent(task, available, ctx)
    if (r.action === 'SOLO_REASSIGN') {
      newAssignments[id] = r.assignee
      tierChanges[id] = [task.currentTier, r.tier]
      available.removeCommitment(r.assignee)
      trace.push({
        taskId: id, action: 'REASSIGN', reason: `Solo reassignment to ${r.assignee} at tier ${r.tier}`,
        oldTier: task.currentTier, newTier: r.tier, oldAssignee: task.assignee, newAssignee: r.assignee,
        qualityChange: [currentQuality(task), q(task, r.tier)],
      })
    } else if (r.action === 'COALITION_FORM') {
      newAssignments[id] = r.coalition
      tierChanges[id] = [task.currentTier, r.tier]
      for (const m of r.coalition.members) available.removeCommitment(m)
      trace.push({
        taskId: id, action: 'DEGRADE', reason: `Coalition [${r.coalition.members.join(', ')}] at tier ${r.tier}`,
        oldTier: task.currentTier, newTier: r.tier, oldAssignee: task.assignee, newAssignee: r.coalition,
        qualityChange: [currentQuality(task), q(task, r.tier)],
      })
    } else {
      abandoned.push(id)
      const freedIds = ledger.releaseTaskResources(task)
      available.addFreed(knownNodes.filter((n) => freedIds.includes(n.nodeId) && n.nodeId !== trigger.sourceNode))
      trace.push({
        taskId: id, action: 'ABANDON', reason: 'No tier satisfiable.', oldTier: task.currentTier, newTier: null,
        oldAssignee: task.assignee, newAssignee: null, qualityChange: [currentQuality(task), 0],
      })
      if (task.def.priorityClass === 'CRITICAL') {
        trace.push({
          taskId: id, action: 'ALARM', reason: 'CRITICAL task abandoned — mission integrity compromised',
          oldTier: null, newTier: null, oldAssignee: null, newAssignee: null, qualityChange: null,
        })
      }
    }
  }

  for (let round = 0; round < DEGRADATION_CASCADE_LIMIT; round++) {
    const upgrades = attemptUpgrades(all, available, ctx)
    if (upgrades.length === 0) break
    for (const [task, newTier, assignee] of upgrades) {
      const id = task.def.taskId
      tierChanges[id] = [task.currentTier, newTier]
      newAssignments[id] = assignee
      trace.push({
        taskId: id, action: 'UPGRADE', reason: `Cascaded upgrade to tier ${newTier}`, oldTier: task.currentTier, newTier,
        oldAssignee: task.assignee, newAssignee: assignee, qualityChange: [currentQuality(task), q(task, newTier)],
      })
    }
  }

  return {
    trigger, affectedTasks: affected.map((t) => t.def.taskId), tierChanges, newAssignments, abandonedTasks: abandoned,
    utilityBefore, utilityAfter: utilityWithChanges(all, tierChanges, abandoned), decisionTrace: trace,
  }
}
