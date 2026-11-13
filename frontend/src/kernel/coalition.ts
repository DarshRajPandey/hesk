/** Port of src/hesk/coalitions/formation.py — Algorithm 005, coalition formation. */
import { checkEligibility, compare } from './matching'
import type { CapabilityState, DataFlowRequirement, DimType, DimValue, LinkMetrics, NodeId, TaskRequirement } from './types'

export const CAPACITY_OVERHEAD_FRACTION = 0.05
export const C_COORD = 0.1
export const C_FRAG = 0.15

export type CompositionSemantic = 'MAX' | 'SUM_DIVISIBLE' | 'UNION'
export type ComposedValue = DimValue | string[]

export interface ComposedCapabilityState {
  members: NodeId[]
  composedValues: Record<string, ComposedValue>
  providerMap: Record<string, NodeId>
}

export interface DataFlowLink {
  sourceNode: NodeId
  sinkNode: NodeId
  requiredBwKbps: number
  /** null encodes "same node" (infinite bandwidth in the Python kernel). */
  availableBwKbps: number | null
  latencyMs: number
  feasible: boolean
}

export interface Coalition {
  coalitionId: string
  taskId: string
  members: NodeId[]
  initiator: NodeId
  roleAssignment: Record<string, NodeId>
  composedState: ComposedCapabilityState
  dataFlowPlan: DataFlowLink[]
  estimatedCost: number
  formationTime: number
  status: 'FORMING' | 'ACTIVE' | 'DEGRADED' | 'DISSOLVED'
}

export interface CoalitionResult {
  success: boolean
  coalition?: Coalition
  rejectionReason?: string
  candidatesTried: number
  covered?: string[]
  missing?: string[]
}

export function compositionSemantic(t: DimType): CompositionSemantic {
  if (t === 'CAPACITY') return 'SUM_DIVISIBLE'
  if (t === 'CATEGORICAL') return 'UNION'
  return 'MAX'
}

function meets(v: ComposedValue | undefined, req: TaskRequirement): boolean {
  if (v === undefined) return false
  return compare(v, req).met
}

const num = (v: DimValue | undefined): number => (typeof v === 'boolean' ? (v ? 1 : 0) : Number(v))

/** First maximum wins, as Python's max() does. */
function argmax(members: CapabilityState[], d: string): CapabilityState {
  let best = members[0] as CapabilityState
  for (const m of members) if (num(m.dimensions[d]) > num(best.dimensions[d])) best = m
  return best
}

export function composeCapabilities(members: CapabilityState[], required: Record<string, TaskRequirement>): ComposedCapabilityState {
  const composed: Record<string, ComposedValue> = {}
  const providers: Record<string, NodeId> = {}
  for (const [d, req] of Object.entries(required)) {
    const valid = members.filter((m) => m.dimensions[d] !== undefined)
    if (valid.length === 0) continue
    const sem = compositionSemantic(req.dimType)
    if (sem === 'MAX') {
      const best = argmax(valid, d)
      composed[d] = best.dimensions[d] as DimValue
      providers[d] = best.nodeId
    } else if (sem === 'SUM_DIVISIBLE') {
      const raw = valid.reduce((s, m) => s + num(m.dimensions[d]), 0)
      composed[d] = raw * (1 - CAPACITY_OVERHEAD_FRACTION * members.length)
      providers[d] = argmax(valid, d).nodeId
    } else {
      const set = new Set<string>()
      for (const m of valid) {
        const v = m.dimensions[d]
        if (typeof v === 'string') set.add(v)
      }
      composed[d] = [...set].sort()
      const p = valid.find((m) => meets(m.dimensions[d], req))
      if (p) providers[d] = p.nodeId
    }
  }
  const composedValues: Record<string, ComposedValue> = {}
  for (const [k, v] of Object.entries(composed)) if (k in providers) composedValues[k] = v
  return { members: members.map((m) => m.nodeId), composedValues, providerMap: providers }
}

function avgInverseBandwidth(node: CapabilityState, members: CapabilityState[], metrics: LinkMetrics): number {
  let total = 0
  let valid = 0
  for (const m of members) {
    const bw = metrics.getBandwidth(node.nodeId, m.nodeId)
    if (bw > 0) {
      total += 1 / bw
      valid += 1
    }
  }
  return valid === 0 ? Infinity : total / valid
}

export function estimateCoalitionCost(memberCount: number, plan: DataFlowLink[]): number {
  let transfer = 0
  for (const f of plan) {
    if (f.sourceNode !== f.sinkNode && f.availableBwKbps !== null && f.availableBwKbps > 0) {
      transfer += (f.requiredBwKbps * 60) / f.availableBwKbps
    }
  }
  return 0.8 + transfer + C_COORD * memberCount + C_FRAG * (memberCount - 1)
}

export interface FormCoalitionArgs {
  taskId: string
  required: Record<string, TaskRequirement>
  dataFlows: DataFlowRequirement[]
  candidates: CapabilityState[]
  linkMetrics: LinkMetrics
  initiatorId: string
  kMax?: number
  /** Deterministic replacements for uuid4() and time.time() in the Python kernel. */
  coalitionId?: string
  now?: number
}

export function formCoalition(a: FormCoalitionArgs): CoalitionResult {
  const { required, candidates, linkMetrics } = a
  const kMax = a.kMax ?? 4
  const gap = new Set(Object.keys(required))
  const members: CapabilityState[] = []
  const available = [...candidates]

  // Phase 1 — greedy incremental construction
  while (gap.size > 0 && members.length < kMax && available.length > 0) {
    let bestScore = -1
    let best: CapabilityState | null = null
    const current = members.length > 0 ? composeCapabilities(members, required) : null
    for (const n of available) {
      let filled = 0
      const temp = composeCapabilities([...members, n], required)
      for (const d of gap) {
        const req = required[d] as TaskRequirement
        const val = temp.composedValues[d]
        if (meets(val, req)) {
          filled += 1
        } else if (req.dimType === 'CAPACITY') {
          const oldVal = current ? Number(current.composedValues[d] ?? 0) : 0
          const newVal = val === undefined ? 0 : Number(val)
          if (newVal > oldVal && req.threshold && req.threshold > 0) filled += Math.min((newVal - oldVal) / req.threshold, 0.99)
        }
      }
      if (filled <= 0) continue
      let comm = 0
      if (members.length > 0) {
        comm = avgInverseBandwidth(n, members, linkMetrics)
        if (comm === Infinity) continue
      }
      const score = filled / (1 + comm)
      if (score > bestScore) {
        bestScore = score
        best = n
      }
    }
    if (best === null) break
    members.push(best)
    available.splice(available.indexOf(best), 1)
    const now = composeCapabilities(members, required)
    for (const d of [...gap]) if (meets(now.composedValues[d], required[d] as TaskRequirement)) gap.delete(d)
  }

  const tried = candidates.length - available.length
  // Phase 2 — verification
  if (gap.size > 0) {
    const missing = [...gap].sort()
    return {
      success: false, rejectionReason: `Cannot cover dimensions: ${missing.join(', ')}`, candidatesTried: tried,
      covered: Object.keys(required).filter((d) => !gap.has(d)), missing,
    }
  }
  const composedState = composeCapabilities(members, required)
  if (!checkEligibility({ dimensions: composedState.composedValues }, required)) {
    return { success: false, rejectionReason: 'Composed state fails eligibility', candidatesTried: tried }
  }

  // Phase 3 — communication feasibility
  const plan: DataFlowLink[] = []
  for (const flow of a.dataFlows) {
    const src = composedState.providerMap[flow.sourceCapability]
    const sink = composedState.providerMap[flow.sinkCapability]
    if (src === undefined || sink === undefined) {
      return { success: false, rejectionReason: `No provider for ${flow.sourceCapability} or ${flow.sinkCapability}`, candidatesTried: tried }
    }
    if (src === sink) {
      plan.push({ sourceNode: src, sinkNode: sink, requiredBwKbps: flow.bandwidthKbps, availableBwKbps: null, latencyMs: 0, feasible: true })
      continue
    }
    const bw = linkMetrics.getBandwidth(src, sink)
    const lat = linkMetrics.getLatency(src, sink)
    const ok = bw >= flow.bandwidthKbps && (flow.maxLatencyMs === undefined || lat <= flow.maxLatencyMs)
    if (!ok) return { success: false, rejectionReason: `Link ${src}->${sink} infeasible`, candidatesTried: tried }
    plan.push({ sourceNode: src, sinkNode: sink, requiredBwKbps: flow.bandwidthKbps, availableBwKbps: bw, latencyMs: lat, feasible: true })
  }

  // Phase 4 — cost estimation
  const coalition: Coalition = {
    coalitionId: a.coalitionId ?? `coal-${a.taskId}`,
    taskId: a.taskId,
    members: members.map((m) => m.nodeId),
    initiator: a.initiatorId,
    roleAssignment: composedState.providerMap,
    composedState,
    dataFlowPlan: plan,
    estimatedCost: estimateCoalitionCost(members.length, plan),
    formationTime: a.now ?? 0,
    status: 'FORMING',
  }
  return { success: true, coalition, candidatesTried: tried }
}
