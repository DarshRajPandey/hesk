/**
 * TypeScript port of the HESK kernel data model.
 * Mirrors src/hesk/core/types.py, capabilities/model.py and tasks/model.py.
 * This port exists so the laboratory can run without a backend; the Python
 * package remains the reference implementation (see tests/parity.test.ts).
 */

export type DimType = 'BOOLEAN' | 'CONTINUOUS' | 'CAPACITY' | 'CATEGORICAL'
export type PriorityClass = 'CRITICAL' | 'IMPORTANT' | 'OPTIONAL'
export type NodeId = string
export type TaskId = string
export type DimValue = number | boolean | string

export interface CapabilityState {
  nodeId: NodeId
  timestamp: number
  dimensions: Record<string, DimValue>
}

export interface TaskRequirement {
  dimType: DimType
  value?: boolean
  threshold?: number
  requiredSet?: string[]
}

export interface DataFlowRequirement {
  sourceCapability: string
  sinkCapability: string
  bandwidthKbps: number
  maxLatencyMs?: number
}

export interface DegradationTier {
  tierLevel: number
  qualityEstimate: number
  label?: string
  required: Record<string, TaskRequirement>
  preferred: Record<string, TaskRequirement>
  dataFlow: DataFlowRequirement[]
}

export interface TaskDefinition {
  taskId: TaskId
  code?: string
  name?: string
  priorityClass: PriorityClass
  missionPriority: number
  qMin: number
  tiers: DegradationTier[]
}

/** Port of TaskDefinition.__post_init__ validation. Throws on an invalid definition. */
export function validateTaskDefinition(t: TaskDefinition): void {
  if (!(t.missionPriority > 0 && t.missionPriority <= 1)) throw new Error('mission_priority must be in (0, 1]')
  if (!(t.qMin >= 0 && t.qMin <= 1)) throw new Error('q_min must be in [0, 1]')
  if (t.tiers.length === 0) throw new Error('Task must have at least one DegradationTier')
  let expected = 0
  let prev = 1.000001
  for (const tier of t.tiers) {
    if (tier.tierLevel !== expected) throw new Error(`Tiers must be contiguous starting from 0 (${t.taskId})`)
    if (tier.qualityEstimate >= prev) throw new Error(`Tier ${tier.tierLevel} quality must strictly decrease (${t.taskId})`)
    if (tier.qualityEstimate < t.qMin) throw new Error(`Tier ${tier.tierLevel} quality below q_min (${t.taskId})`)
    expected += 1
    prev = tier.qualityEstimate
  }
}

export interface LinkMetrics {
  getBandwidth(source: NodeId, sink: NodeId): number
  getLatency(source: NodeId, sink: NodeId): number
}

export const TaskStatus = {
  EXECUTING: 'EXECUTING',
  DEGRADED: 'DEGRADED',
  ABANDONED: 'ABANDONED',
  COMPLETED: 'COMPLETED',
} as const
export type TaskStatusT = (typeof TaskStatus)[keyof typeof TaskStatus]
