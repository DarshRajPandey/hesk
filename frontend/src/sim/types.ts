/** Plain-data view of the simulated world. This is the contract between any simulation source and the UI. */
import type { DataFlowLink } from '../kernel/coalition'
import type { DimValue, PriorityClass, TaskStatusT } from '../kernel/types'
import type { ArchetypeId, PresetId } from './catalog'

export type Health = 'NOMINAL' | 'DEGRADED' | 'DEPLETED' | 'FAILED'
export type Severity = 'info' | 'ok' | 'warn' | 'crit'
/** Who produced a record: the ported kernel algorithm, the simulation harness around it, or the operator. */
export type Source = 'kernel' | 'harness' | 'operator'

export interface NodeRole {
  taskId: string
  tier: number
  kind: 'SOLO' | 'COALITION'
  provides: string[]
}

export interface NodeView {
  id: string
  archetype: ArchetypeId
  x: number
  y: number
  alive: boolean
  depleted: boolean
  isolated: boolean
  health: Health
  energy: number
  dims: Record<string, DimValue>
  baseDims: Record<string, DimValue>
  replicaId: string | null
  role: NodeRole | null
  neighbours: string[]
  joinedTick: number
}

export interface LinkView {
  a: string
  b: string
  distance: number
  bandwidthKbps: number
  latencyMs: number
  up: boolean
}

export interface TaskView {
  taskId: string
  code: string
  name: string
  priorityClass: PriorityClass
  missionPriority: number
  tierCount: number
  tier: number
  tierLabel: string
  status: TaskStatusT
  kind: 'SOLO' | 'COALITION' | 'NONE'
  members: string[]
  roles: Record<string, string>
  flows: DataFlowLink[]
  quality: number
  progress: number
  matchQuality: number
  /** True when every assigned node is alive and mutually connected, i.e. the task is physically running. */
  live: boolean
}

export interface LedgerRow {
  key: string
  type: string
  digest: string
  source: string
  clock: number
  conflict: boolean
}

export interface ReplicaView {
  id: string
  members: string[]
  lamport: number
  seq: number
  versionVector: Record<string, number>
  eventCount: number
  utility: number
  tasks: TaskView[]
  ledger: LedgerRow[]
}

export type EventKind =
  | 'BOOT' | 'AUCTION' | 'COALITION' | 'REASSIGN' | 'DEGRADE' | 'ABANDON' | 'UPGRADE' | 'ALARM'
  | 'FAULT' | 'RECOVERY' | 'DETECT' | 'PARTITION' | 'RECONCILE' | 'CONFLICT' | 'JOIN' | 'TOPOLOGY'

export interface SimEvent {
  id: number
  tick: number
  kind: EventKind
  severity: Severity
  source: Source
  title: string
  detail?: string
  nodeIds: string[]
  taskId?: string
  replicaId?: string
  algo?: string
}

export interface MetricSample {
  tick: number
  utility: number
  maxUtility: number
  utilityRatio: number
  activeNodes: number
  failedNodes: number
  components: number
  connectivity: number
  links: number
  messages: number
  msgBeacon: number
  msgCoordination: number
  msgReconcile: number
  busyRatio: number
  meanEnergy: number
  duplicated: number
  agreement: number
  tasksFull: number
  tasksDegraded: number
  tasksAbandoned: number
  latencyFactor: number
}

export interface AuctionBid {
  nodeId: string
  cost: number
  quality: number
  energy: number
  scarcityPenalty: number
}

export interface AuctionRound {
  id: number
  tick: number
  replicaId: string
  taskId: string
  tier: number
  participants: number
  bids: AuctionBid[]
  ineligible: Array<{ nodeId: string; unmet: string[] }>
  outcome: 'SOLO' | 'COALITION' | 'UNFILLED'
  winner: string | null
  runnerUp: string | null
  coalition: string[] | null
  coalitionNote: string | null
}

export interface ConflictView {
  key: string
  type: string
  local: string
  remote: string
  strategy: string
  winner: string
  reason: string
  sideEffects: string[]
}

export interface ReconciliationRecord {
  id: number
  tick: number
  survivor: string
  absorbed: string
  survivorMembers: string[]
  absorbedMembers: string[]
  eventsToSurvivor: number
  eventsToAbsorbed: number
  mergedForward: number
  mergedReverse: number
  conflicts: ConflictView[]
  transferred: number
  divergedKeys: string[]
  converged: boolean
  /** Ticks between the physical link change and reconciliation completing. */
  ticksSinceChange: number
  /** Wall-clock cost of both reconciliation passes in this browser. Not deterministic. */
  wallMs: number
}

export type FaultKind = 'NODE_FAILURE' | 'PARTITION' | 'LATENCY' | 'RECOVERY' | 'JOIN' | 'CAPABILITY' | 'REMOVE' | 'HEAL'

export interface FaultRecord {
  id: number
  tick: number
  kind: FaultKind
  label: string
  nodeIds: string[]
  utilityBefore: number
  respondedTick: number | null
  utilityAfter: number | null
}

export interface WorldSnapshot {
  tick: number
  timeS: number
  seed: number
  preset: PresetId
  tickSeconds: number
  detectTicks: number
  latencyFactor: number
  cut: { axis: 'x' | 'y'; at: number } | null
  pendingDetection: number | null
  nodes: NodeView[]
  links: LinkView[]
  replicas: ReplicaView[]
  taskIds: string[]
  events: SimEvent[]
  metrics: MetricSample[]
  auctions: AuctionRound[]
  reconciliations: ReconciliationRecord[]
  faults: FaultRecord[]
}

export type Command =
  | { type: 'step' }
  | { type: 'reset'; preset: PresetId; seed: number }
  | { type: 'addNode'; archetype: ArchetypeId; x?: number; y?: number }
  | { type: 'removeNode'; id: string }
  | { type: 'failNode'; id: string }
  | { type: 'recoverNode'; id: string }
  | { type: 'degradeCapability'; id: string; dim: string; factor: number }
  | { type: 'restoreCapabilities'; id: string }
  | { type: 'setCut'; axis: 'x' | 'y'; at: number }
  | { type: 'clearCut' }
  | { type: 'isolateNode'; id: string }
  | { type: 'rejoinNode'; id: string }
  | { type: 'setLatencyFactor'; factor: number }
