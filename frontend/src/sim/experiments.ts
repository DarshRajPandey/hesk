/** Scripted fault-injection experiments. Each is a deterministic command schedule over a preset. */
import type { PresetId } from './catalog'
import type { Command, WorldSnapshot } from './types'

export type PhaseId = 'INITIAL' | 'TRIGGER' | 'RESPONSE' | 'RECOVERY' | 'FINAL'
export const PHASES: Array<{ id: PhaseId; label: string }> = [
  { id: 'INITIAL', label: 'Initial state' },
  { id: 'TRIGGER', label: 'Triggered event' },
  { id: 'RESPONSE', label: 'System response' },
  { id: 'RECOVERY', label: 'Recovery behaviour' },
  { id: 'FINAL', label: 'Final state' },
]

export interface ExperimentStep {
  at: number
  phase: PhaseId
  note: string
  /** Resolved against the live snapshot so scripts can target "whoever holds task X". */
  command?: (s: WorldSnapshot, memo: Record<string, string>) => Command | null
}

export interface ExperimentDef {
  id: string
  index: number
  title: string
  faultClass: string
  question: string
  preset: PresetId
  seed: number
  duration: number
  /** Which kernel code path the experiment exercises. */
  exercises: string
  /** What the result does and does not show. */
  caveat: string
  steps: ExperimentStep[]
}

const holder = (s: WorldSnapshot, taskId: string): string | null =>
  s.replicas[0]?.tasks.find((t) => t.taskId === taskId)?.members[0] ?? null

const T = 4 // trigger tick
const D = 2 // detection delay (engine DETECT_TICKS)
const R = 12 // recovery tick

export const EXPERIMENTS: ExperimentDef[] = [
  {
    id: 'node-failure', index: 1, title: 'Node failure', faultClass: 'Loss of a high-value node',
    question: 'What happens to a CRITICAL task when the only node able to do it alone disappears?',
    preset: 'quintet', seed: 7, duration: 20,
    exercises: '006 graceful degradation · NODE_LOSS trigger → tier descent → solo or coalition → abandon',
    caveat: 'Detection delay is a harness parameter. The kernel never pre-empts lower-priority work, so a CRITICAL task can be abandoned while an IMPORTANT one keeps its node.',
    steps: [
      { at: 0, phase: 'INITIAL', note: 'Five heterogeneous nodes, four mission tasks auctioned.' },
      { at: T, phase: 'TRIGGER', note: 'The node executing area mapping fails silently.', command: (s, m) => { const id = holder(s, 'map_zone'); if (!id) return null; m.target = id; return { type: 'failNode', id } } },
      { at: T + D, phase: 'RESPONSE', note: 'Peers miss two beacons; the degradation planner runs.' },
      { at: R, phase: 'RECOVERY', note: 'The failed node reboots with an empty ledger.', command: (_s, m) => (m.target ? { type: 'recoverNode', id: m.target } : null) },
      { at: R + D + 2, phase: 'FINAL', note: 'State transferred to the rejoined node; upgrade pass complete.' },
    ],
  },
  {
    id: 'partition', index: 2, title: 'Network partition', faultClass: 'Split-brain and reconciliation',
    question: 'Do two halves of a jammed swarm keep working, and do they agree again after the jam lifts?',
    preset: 'baseline', seed: 7, duration: 24,
    exercises: '007 ledger fork · 006 LINK_LOSS on both sides · 008 handle_reconnection with ownership cascade',
    caveat: 'One ledger is kept per connected component. Convergence is checked by running reconciliation on both sides and comparing the results, not assumed.',
    steps: [
      { at: 0, phase: 'INITIAL', note: 'Twelve nodes in one connected component, one shared ledger state.' },
      { at: T, phase: 'TRIGGER', note: 'Every link crossing the east/west line is jammed.', command: () => ({ type: 'setCut', axis: 'x', at: 0.5 }) },
      { at: T + D, phase: 'RESPONSE', note: 'Each side forks the ledger and re-plans the tasks it can no longer see.' },
      { at: 14, phase: 'RECOVERY', note: 'Jamming lifted. Both sides hold contradictory ownership claims.', command: () => ({ type: 'clearCut' }) },
      { at: 14 + D + 2, phase: 'FINAL', note: 'Reconciliation resolved every dual-ownership conflict.' },
    ],
  },
  {
    id: 'latency', index: 3, title: 'Communication latency', faultClass: 'Degraded links',
    question: 'How does rising link latency change what the swarm can do?',
    preset: 'baseline', seed: 7, duration: 24,
    exercises: '005 coalition data-flow feasibility (max_latency_ms) · 006 LINK_LOSS re-plan · upgrade pass',
    caveat: 'Latency reaches the kernel only through coalition data-flow limits. Message delay, loss and staleness-weighted confidence are not exercised by this harness.',
    steps: [
      { at: 0, phase: 'INITIAL', note: 'Setup: both heavy ISR nodes are removed so mapping must run as a coalition.', command: () => ({ type: 'removeNode', id: 'ISR-1' }) },
      { at: 1, phase: 'INITIAL', note: 'Setup: second ISR node removed.', command: () => ({ type: 'removeNode', id: 'ISR-2' }) },
      { at: 8, phase: 'TRIGGER', note: 'Latency on every link multiplied by four.', command: () => ({ type: 'setLatencyFactor', factor: 4 }) },
      { at: 9, phase: 'RESPONSE', note: 'Coalition data flows exceed their latency limit; tasks descend to tiers without streaming.' },
      { at: 16, phase: 'RECOVERY', note: 'Latency returns to nominal.', command: () => ({ type: 'setLatencyFactor', factor: 1 }) },
      { at: 20, phase: 'FINAL', note: 'Upgrade pass re-forms the coalitions.' },
    ],
  },
  {
    id: 'recovery', index: 4, title: 'Node recovery', faultClass: 'Fail, substitute, return',
    question: 'When a specialist node comes back, does the swarm hand its role back?',
    preset: 'quintet', seed: 7, duration: 20,
    exercises: '006 reassignment at a lower tier · 008 state transfer to an empty ledger · attempt_upgrades',
    caveat: 'Restarting work after a node returns is harness policy built from kernel functions; the kernel defines no rejoin protocol.',
    steps: [
      { at: 0, phase: 'INITIAL', note: 'The relay node holds the mesh-relay task at full quality.' },
      { at: T, phase: 'TRIGGER', note: 'The relay node fails.', command: (s, m) => { const id = holder(s, 'comms_relay'); if (!id) return null; m.target = id; return { type: 'failNode', id } } },
      { at: T + D, phase: 'RESPONSE', note: 'A generalist inherits the role at a degraded tier.' },
      { at: R, phase: 'RECOVERY', note: 'The relay node comes back online.', command: (_s, m) => (m.target ? { type: 'recoverNode', id: m.target } : null) },
      { at: R + D + 2, phase: 'FINAL', note: 'Upgrade pass returns the task to tier 0.' },
    ],
  },
  {
    id: 'join', index: 5, title: 'New node joining', faultClass: 'Changing team composition',
    question: 'Can a node that was never part of the mission be absorbed and put to work?',
    preset: 'quintet', seed: 7, duration: 18,
    exercises: '008 reconciliation against an empty replica · 003/004 re-auction · attempt_upgrades',
    caveat: 'Discovery is modelled as hearing a beacon. Capability advertisement and authentication of a joining node are not part of HESK today.',
    steps: [
      { at: 0, phase: 'INITIAL', note: 'Target tracking runs degraded: the only heavy ISR node is busy mapping.' },
      { at: T, phase: 'TRIGGER', note: 'A second heavy ISR node powers on inside radio range.', command: () => ({ type: 'addNode', archetype: 'ISR', x: 0.62, y: 0.46 }) },
      { at: T + D, phase: 'RESPONSE', note: 'The newcomer is discovered, receives ledger state and is offered work.' },
      { at: 10, phase: 'RECOVERY', note: 'No recovery action: joining is a gain, not a fault.' },
      { at: 14, phase: 'FINAL', note: 'Steady state with six nodes.' },
    ],
  },
  {
    id: 'capability', index: 6, title: 'Capability degradation', faultClass: 'Partial hardware failure',
    question: 'A node is alive but one sensor is failing. Does the swarm keep the most useful version of the task?',
    preset: 'quintet', seed: 7, duration: 20,
    exercises: '001 runtime capability vs inventory · 006 CAPABILITY_DEGRADATION trigger · tier descent · attempt_upgrades',
    caveat: 'The kernel excludes the degraded node from its own re-plan; the harness then re-auctions so the node can take a tier it still satisfies.',
    steps: [
      { at: 0, phase: 'INITIAL', note: 'The heavy ISR node produces a dense 3D map (tier 0).' },
      { at: T, phase: 'TRIGGER', note: 'Its camera degrades to half effectiveness.', command: (s, m) => { const id = holder(s, 'map_zone'); if (!id) return null; m.target = id; return { type: 'degradeCapability', id, dim: 'camera', factor: 0.5 } } },
      { at: T + 1, phase: 'RESPONSE', note: 'Self-reported, so the response is immediate: mapping descends to a tier the node still satisfies.' },
      { at: R, phase: 'RECOVERY', note: 'The sensor is restored.', command: (_s, m) => (m.target ? { type: 'restoreCapabilities', id: m.target } : null) },
      { at: R + 3, phase: 'FINAL', note: 'Upgrade pass returns mapping to tier 0.' },
    ],
  },
]

export const experimentById = (id: string): ExperimentDef | undefined => EXPERIMENTS.find((e) => e.id === id)
