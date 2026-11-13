/** Port of src/hesk/tasks/allocation.py — Algorithm 004, scarcity-aware allocation. */
import type { CapabilityState, DimValue, NodeId, TaskId } from './types'

export interface Bid {
  taskId: TaskId
  nodeId: NodeId
  systemCost: number
  matchQuality: number
  energy: number
  scarcityPenalty: number
}

export interface AllocationResult {
  taskId: TaskId
  assignedNode: NodeId | null
  systemCost: number | null
  matchQuality: number | null
  runnerUpNode: NodeId | null
  runnerUpCost: number | null
  bidsReceived: number
}

/** Python treats bool as int, so True counts as 1 and False as 0. Strings are not numeric. */
function numeric(v: DimValue | undefined): number | null {
  if (typeof v === 'number') return v
  if (typeof v === 'boolean') return v ? 1 : 0
  return null
}

export function computeScarcity(dimension: string, swarm: CapabilityState[], theta = 0.1): number {
  if (swarm.length === 0) return 1
  let meaningful = 0
  for (const s of swarm) {
    const n = numeric(s.dimensions[dimension])
    if (n !== null && n >= theta) meaningful += 1
  }
  return 1 - meaningful / swarm.length
}

/** theta for a dimension as the kernel derives it: 10% of the swarm maximum (0.1 if none). */
export function dynamicTheta(dimension: string, swarm: CapabilityState[]): number {
  let max = 0
  for (const s of swarm) {
    const n = numeric(s.dimensions[dimension])
    if (n !== null && n > max) max = n
  }
  return max > 0 ? max * 0.1 : 0.1
}

export function computeExecCost(matchQuality: number, energy: number): number {
  return 1 - matchQuality + (1 - energy)
}

export function computeEnergyCost(baseConsumption: number, energy: number): number {
  return energy <= 0 ? Infinity : baseConsumption / energy
}

export function computeScarcityPenalty(own: CapabilityState, requiredDims: Set<string>, swarm: CapabilityState[]): number {
  let penalty = 0
  for (const [dim, val] of Object.entries(own.dimensions)) {
    if (requiredDims.has(dim)) continue
    const theta = dynamicTheta(dim, swarm)
    const n = numeric(val)
    if (n !== null && n >= theta) penalty += computeScarcity(dim, swarm, theta)
  }
  return penalty
}

export function computeSystemCost(
  matchQuality: number, energy: number, baseConsumption: number, scarcityPenalty: number,
  commCost = 0, wExec = 1, wEnergy = 0.5, wScarcity = 2, wComm = 0,
): number {
  return wExec * computeExecCost(matchQuality, energy) + wEnergy * computeEnergyCost(baseConsumption, energy)
    + wScarcity * scarcityPenalty + wComm * commCost
}

/** Lowest system cost wins; ties break on quality (desc), energy (desc), node id (asc). */
export function evaluateBids(bids: Bid[], taskId: TaskId): AllocationResult {
  if (bids.length === 0) {
    return { taskId, assignedNode: null, systemCost: null, matchQuality: null, runnerUpNode: null, runnerUpCost: null, bidsReceived: 0 }
  }
  const sorted = [...bids].sort((a, b) =>
    a.systemCost - b.systemCost || b.matchQuality - a.matchQuality || b.energy - a.energy || (a.nodeId < b.nodeId ? -1 : a.nodeId > b.nodeId ? 1 : 0))
  const w = sorted[0] as Bid
  const r = sorted[1]
  return {
    taskId, assignedNode: w.nodeId, systemCost: w.systemCost, matchQuality: w.matchQuality,
    runnerUpNode: r ? r.nodeId : null, runnerUpCost: r ? r.systemCost : null, bidsReceived: bids.length,
  }
}
