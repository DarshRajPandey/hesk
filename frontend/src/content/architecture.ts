/**
 * Architecture inventory. Every statement here was checked against the
 * repository (source, tests, and probes run against the Python package).
 */
export type Status = 'implemented' | 'partial' | 'planned' | 'unavailable'

export interface ArchComponent {
  id: string
  code: string
  name: string
  status: Status
  /** Which of the brief's concepts this component realises. */
  concept: string
  purpose: string
  inputs: string[]
  outputs: string[]
  source: string[]
  tests: string
  lab: string
  gaps: string[]
  /** Diagram placement on a 12 × 5 grid. */
  col: number
  row: number
}

export const STATUS_META: Record<Status, { label: string; color: string; meaning: string }> = {
  implemented: { label: 'Implemented', color: 'var(--color-ok)', meaning: 'Code and unit tests exist in src/hesk.' },
  partial: { label: 'Partial', color: 'var(--color-warn)', meaning: 'Some code exists; important parts are stubbed or missing.' },
  planned: { label: 'Planned', color: 'var(--color-blue)', meaning: 'Named in the README or repository layout; no code yet.' },
  unavailable: { label: 'Unavailable', color: 'var(--color-ink-3)', meaning: 'Not in the repository and not specified.' },
}

export const COMPONENTS: ArchComponent[] = [
  {
    id: 'discovery', code: '—', name: 'Capability discovery & transport', status: 'unavailable', concept: 'Capability discovery', col: 0, row: 0,
    purpose: 'How a node learns that peers exist and what they can currently do: beacons, capability advertisement, message transport.',
    inputs: ['Radio / middleware messages'], outputs: ['CapabilityState and LinkState reports for peers'],
    source: [], tests: 'none',
    lab: 'Simulated by the harness: a node is "heard" when it is within radio range, after a fixed detection delay.',
    gaps: ['No networking, serialisation or ROS 2 binding exists.', 'LinkState is defined as a dataclass but nothing produces it.', 'LinkMetrics in coalitions/formation.py is a mock returning infinite bandwidth.'],
  },
  {
    id: 'cap', code: '001', name: 'Capability model', status: 'implemented', concept: 'Capability discovery', col: 3, row: 0,
    purpose: 'Describes what a node can do right now, per typed dimension (boolean, continuous, capacity, categorical), rather than what hardware it carries.',
    inputs: ['Per-node dimension values'], outputs: ['CapabilityState (immutable, timestamped)'],
    source: ['src/hesk/capabilities/model.py', 'src/hesk/core/types.py'], tests: '5 unit tests (test_capabilities, test_types)',
    lab: 'Every simulated node carries a CapabilityState; the Node Inspector shows it as a vector with its baseline.',
    gaps: ['No runtime derivation from thermal, energy or load — values are supplied by the caller.'],
  },
  {
    id: 'task', code: '002', name: 'Task model', status: 'implemented', concept: 'Capability-aware coordination', col: 6, row: 0,
    purpose: 'Represents a mission task as required and preferred capabilities with an ordered list of degradation tiers and a minimum acceptable quality.',
    inputs: ['Mission definition'], outputs: ['TaskDefinition with validated DegradationTiers'],
    source: ['src/hesk/tasks/model.py'], tests: '8 unit tests (test_tasks)',
    lab: 'Six mission tasks in the scenario catalog, validated with the same rules as the Python model.',
    gaps: ['ActiveTask.with_tier() is a stub that returns the definition unchanged.'],
  },
  {
    id: 'match', code: '003', name: 'Capability matching', status: 'implemented', concept: 'Capability-aware coordination', col: 3, row: 1,
    purpose: 'Decides whether a node can execute a task tier (required dimensions) and how well (preferred dimensions), discounted by how stale the report is.',
    inputs: ['CapabilityState', 'Tier requirements', 'Report age'], outputs: ['MatchResult: eligible, quality, confidence, unmet dimensions'],
    source: ['src/hesk/capabilities/matching.py'], tests: '2 unit tests + adversarial cases',
    lab: 'Used for every bid and shown per node as the solo-eligibility grid. Parity-tested on 156 node × tier cases.',
    gaps: ['The lab always passes report age 0, so staleness-weighted confidence is not exercised here.'],
  },
  {
    id: 'alloc', code: '004', name: 'Scarcity-aware allocation', status: 'implemented', concept: 'Capability-aware coordination', col: 6, row: 1,
    purpose: 'Scores each eligible node by execution cost, energy cost and a penalty for tying up capabilities that are rare in the swarm and that the task does not need.',
    inputs: ['Bids', 'Known swarm capability states'], outputs: ['AllocationResult: winner, runner-up, costs'],
    source: ['src/hesk/tasks/allocation.py'], tests: '3 unit tests (test_allocation)',
    lab: 'Auction rounds in the Consensus Laboratory. Bid costs match the Python package to 10 decimal places.',
    gaps: ['Bid collection is the caller\'s job — there is no bidding protocol or timeout handling.', 'Communication cost has weight 0 by default.'],
  },
  {
    id: 'coal', code: '005', name: 'Coalition formation', status: 'implemented', concept: 'Capability-aware coordination', col: 9, row: 1,
    purpose: 'When no single node can do a task, greedily assembles up to four nodes whose composed capabilities can, then checks the data-flow links between them.',
    inputs: ['Tier requirements', 'Candidate nodes', 'Link metrics'], outputs: ['Coalition with role assignment and data-flow plan'],
    source: ['src/hesk/coalitions/formation.py', 'src/hesk/coalitions/model.py'], tests: '1 unit test (test_coalitions)',
    lab: 'Coalitions appear on the map as violet data flows; the latency experiment breaks them through max_latency_ms.',
    gaps: ['A coalition can never satisfy a CATEGORICAL requirement: the composed value is a set, which is never a member of the required set (confirmed against the Python package).', 'Per-member execution cost is a fixed placeholder (0.8).'],
  },
  {
    id: 'degr', code: '006', name: 'Graceful degradation', status: 'implemented', concept: 'Graceful degradation', col: 6, row: 2,
    purpose: 'On node, link, energy or capability loss: re-plans affected tasks in priority order — reassign, form a coalition, descend a tier, or abandon — then tries to upgrade degraded tasks.',
    inputs: ['DegradationTrigger', 'Affected tasks', 'Available nodes'], outputs: ['DegradationPlan with tier changes, assignments and a decision trace'],
    source: ['src/hesk/degradation/logic.py', 'src/hesk/degradation/model.py'], tests: '1 unit test (test_degradation)',
    lab: 'Runs on every detected loss. Its decision trace is what the event stream shows as kernel events tagged 006.',
    gaps: ['Reassignment ignores real energy and scarcity (fixed energy 1.0, penalty 0.0), so Algorithm 004 is not applied during recovery.', 'No pre-emption: a CRITICAL task can be abandoned while a lower-priority task keeps a node that could run it.', 'The upgrade cascade does not update task state between rounds; freed_nodes is always empty.', 'The ledger it reads (LocalLedger) is a mock interface, not Algorithm 007.'],
  },
  {
    id: 'succ', code: '—', name: 'Role inheritance', status: 'partial', concept: 'Role inheritance', col: 9, row: 2,
    purpose: 'Explicit succession: who takes over each responsibility of a lost node, and how that hand-over is recorded.',
    inputs: ['Lost node', 'Its responsibilities'], outputs: ['ResponsibilitySuccession record'],
    source: ['src/hesk/degradation/model.py'], tests: 'none',
    lab: 'Shown only as the reassignments produced by Algorithm 006 ("role inherited by …").',
    gaps: ['ResponsibilitySuccession is declared but never constructed or used.', 'No hand-over of in-progress work: a successor starts from zero.'],
  },
  {
    id: 'ledger', code: '007', name: 'Local state ledger', status: 'implemented', concept: 'Distributed consensus', col: 3, row: 3,
    purpose: 'Each node\'s own record of beliefs, with Lamport clocks, provenance and seven semantic types that each merge differently (set union, counter max, exclusive ownership, …).',
    inputs: ['Local writes', 'State received from peers'], outputs: ['Ledger entries', 'Event log', 'Version vector'],
    source: ['src/hesk/ledger/ledger.py', 'src/hesk/ledger/model.py'], tests: '1 unit test (test_ledger)',
    lab: 'One ledger per connected component (HESK specifies one per node). The replica-state table reads it directly.',
    gaps: ['The version vector only tracks a node\'s own writes; it is not advanced when remote state is received.', 'In is_potentially_concurrent the clock-distance clause is subsumed by the wall-time clause.', 'REACHABILITY merge is marked simplistic in the source.'],
  },
  {
    id: 'recon', code: '008', name: 'Partition reconciliation', status: 'implemented', concept: 'State reconciliation', col: 6, row: 3,
    purpose: 'When partitions rejoin: exchange unseen events, merge convergent types, and resolve conflicting claims deterministically — dual task ownership by progress, then match quality, then time, then node id.',
    inputs: ['Local ledger', 'Remote events and version vector'], outputs: ['ReconciliationTrace', 'Side effects (release executor, notify winner)'],
    source: ['src/hesk/ledger/reconciliation.py'], tests: '4 unit tests (test_reconciliation)',
    lab: 'Run from both sides on every merge and the results compared, so convergence is checked rather than assumed.',
    gaps: ['A key changed on only one side of a partition is not merged unless its type is set, counter or observation (confirmed against the Python package). The lab transfers unknown keys separately and flags any remaining difference.', 'Resource conflicts inside the 2 s drift margin with equal provenance scores resolve to "local wins" on each side, so the two sides can keep different values.', 'Divergence point is reported as clock 0 ("simplified" in the source).'],
  },
  {
    id: 'vote', code: '—', name: 'Voting consensus', status: 'unavailable', concept: 'Distributed consensus', col: 0, row: 3,
    purpose: 'Quorum agreement, leader election or Byzantine fault tolerance.',
    inputs: [], outputs: [],
    source: [], tests: 'none',
    lab: 'Not shown. The Consensus Laboratory displays auctions and ledger convergence instead and says so.',
    gaps: ['Not part of the design: HESK is brokerless and resolves disagreement by semantic merge, not by vote.', 'There is no defence against a node that reports false state.'],
  },
  {
    id: 'detect', code: '—', name: 'Failure & partition detection', status: 'unavailable', concept: 'Network partition handling', col: 9, row: 3,
    purpose: 'Deciding that a peer is gone or that the network has split, and turning that into a DegradationTrigger or ReconnectionEvent.',
    inputs: ['Beacon timing'], outputs: ['Triggers for 006 and 008'],
    source: [], tests: 'none',
    lab: 'Harness rule: two missed beacons (10 s simulated). This sets every "recovery latency" figure in the Observatory.',
    gaps: ['Trigger and reconnection types exist; nothing in the kernel raises them.'],
  },
  {
    id: 'sim', code: '—', name: 'Simulation & evaluation harness', status: 'planned', concept: 'Evaluation', col: 0, row: 4,
    purpose: 'The multi-fidelity evaluation plan in the README: 10–1,000 agent Monte Carlo sweeps, then PX4 + ROS 2, Isaac Sim and Jetson Orin.',
    inputs: ['Scenario definitions'], outputs: ['Utility, recovery and convergence measurements'],
    source: ['simulation/ (empty)', 'examples/ (empty)', 'docs/ARCHITECTURE.md (empty)'], tests: 'none',
    lab: 'This laboratory\'s in-browser harness is a stand-in at ≤ 20 nodes. It is not the planned Python simulator.',
    gaps: ['No Monte Carlo runner, no benchmark, no hardware results.'],
  },
  {
    id: 'vehicle', code: '—', name: 'Vehicle & middleware integration', status: 'planned', concept: 'Integration', col: 3, row: 4,
    purpose: 'HESK sits above flight control (PX4) and robotics middleware (ROS 2); the kernel issues coordination decisions, not motion commands.',
    inputs: ['Local observations from the vehicle stack'], outputs: ['Task assignments to the autonomy layer'],
    source: [], tests: 'none',
    lab: 'Not represented. Nodes in the lab do not move.',
    gaps: ['No interface definition exists yet.'],
  },
  {
    id: 'api', code: '—', name: 'Service API for this laboratory', status: 'unavailable', concept: 'Integration', col: 6, row: 4,
    purpose: 'A network interface through which a frontend could observe and command a running HESK swarm.',
    inputs: ['Commands'], outputs: ['World snapshots'],
    source: ['frontend/src/sim/adapter.ts'], tests: 'none',
    lab: 'The UI talks only to a SimulationAdapter interface. Today its one implementation runs in the browser.',
    gaps: ['The Python package exposes functions only — no server, CLI or stream.'],
  },
]

/** Directed data-flow edges between components, by id. */
export const EDGES: Array<[string, string]> = [
  ['discovery', 'cap'], ['cap', 'match'], ['task', 'match'], ['match', 'alloc'], ['alloc', 'coal'], ['alloc', 'degr'], ['coal', 'degr'],
  ['degr', 'succ'], ['degr', 'ledger'], ['ledger', 'recon'], ['recon', 'ledger'], ['detect', 'degr'], ['detect', 'recon'], ['vehicle', 'cap'],
]
