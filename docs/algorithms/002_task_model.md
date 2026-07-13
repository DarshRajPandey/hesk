# 002 — Task Model

**Status:** Algorithm Design  
**Depends on:** 001_capability_model  
**Consumed by:** 003_capability_matching, 004_scarcity_allocation, 005_coalition_formation, 006_graceful_degradation  
**Version:** 0.1  

---

## 1. PROBLEM

A heterogeneous swarm coordination kernel must represent *what needs to be done* with enough structure for decentralized matching, degradation, and coalition formation — yet without requiring global knowledge about which nodes exist or what they can do.

### Why "task needs compute > 0.5" is insufficient

A naive task specification such as:

```
task_mapping = { requires: "compute > 0.5" }
```

fails in multiple ways:

1. **No required/preferred boundary.** A task that *requires* localization ≥ 0.7 to produce any useful output and *prefers* lidar ≥ 0.8 for best quality conflates these into a flat list. When a node has localization 0.8 but no lidar, the system cannot distinguish "degraded but feasible" from "infeasible."

2. **No degradation path.** When the ideal executor is lost, the system has no pre-defined fallback tiers. It must either re-solve from scratch (expensive, unreliable under partition) or fail entirely (wasteful).

3. **No minimum quality floor.** Without a `minimum_acceptable_quality`, nodes may spend energy and bandwidth producing results that are operationally useless — e.g., a mapping pass so sparse it cannot support navigation.

4. **No data flow semantics.** "Needs compute" says nothing about *what data enters the computation, at what rate, from which sensor, and where results must go.* A coalition cannot form without this.

5. **No lifecycle management.** A flat requirement string has no concept of whether a task is pending announcement, under active bidding, assigned, executing, or completed. State machine transitions with preconditions are essential for distributed consistency.

6. **No mission priority semantics.** Binary pass/fail gives no guidance on *which tasks to preserve first* when resources become scarce. A search-and-rescue thermal scan and an optional terrain photograph cannot share the same priority model.

The Task Model defines the **structured, machine-readable representation** of task requirements, quality expectations, degradation paths, data flow dependencies, lifecycle states, and mission priority — providing the vocabulary that downstream algorithms (matching, allocation, coalition, degradation) consume.

---

## 2. DEFINITIONS

### 2.1 Shared Notation

| Symbol | Meaning |
|--------|---------|
| n_i | Node i |
| C_i | Capability state of node i (defined in 001) |
| τ_j | Task j |
| R_j | Full requirement specification of task τ_j |
| R_j^req | Required capabilities — hard constraints |
| R_j^pref | Preferred capabilities — soft constraints |
| π_j | Mission priority of task τ_j ∈ (0, 1] |
| f(n_i, τ_j) | Match score: node i against task j (defined in 003) |
| Γ | Coalition of nodes |
| L_i | Local ledger of node i |
| λ_i | Lamport clock of node i |
| q_min_j | Minimum acceptable quality for task τ_j |

### 2.2 MissionPriorityClass

An enumeration providing coarse-grained priority classification:

```
MissionPriorityClass:
  CRITICAL    // π ∈ [0.80, 1.00] — must be preserved under scarcity
  IMPORTANT   // π ∈ [0.40, 0.80) — preserve if resources permit
  OPTIONAL    // π ∈ (0.00, 0.40) — may be suspended or abandoned
```

The numeric π_j value provides fine-grained ordering *within* a class. Degradation (006) sheds OPTIONAL tasks before IMPORTANT before CRITICAL. Two tasks in the same class are ordered by their exact π_j.

### 2.3 TaskRequirement

The central data structure of this document.

```
TaskRequirement:
  task_id:           string           // globally unique, e.g. "mapping_zone_b"
  description:       string           // human-readable purpose
  required:          Map<dim, threshold>   // R_j^req — must be satisfied
  preferred:         Map<dim, threshold>   // R_j^pref — desired for full quality
  priority:          float ∈ (0, 1]        // π_j — mission priority
  priority_class:    MissionPriorityClass  // derived from π_j
  min_quality:       float ∈ (0, 1]        // q_min_j — below this, don't execute
  degradation_tiers: [DegradationTier]     // ordered T0..Tn, descending quality
  data_flows:        [DataFlowRequirement] // inter-capability data dependencies
  deadline:          Duration | null        // wall-clock budget from execution start
  spatial_constraint: SpatialConstraint | null  // where the task must execute
  created_at:        (node_id, λ)          // provenance: who defined it, when
  version:           integer               // monotonic, incremented on modification
```

**Design note on `dim` keys:** Capability dimensions use hierarchical dot notation matching 001_capability_model — e.g., `sensing.rgb`, `compute.gpu`, `localization`. Threshold semantics depend on dimension type:
- BOOLEAN: threshold is 1.0 (must be present)
- CONTINUOUS [0,1]: capability ≥ threshold
- CAPACITY: absolute value ≥ threshold (units must match)
- CATEGORICAL: capability ∈ required set
- COMPOSITE: recursively evaluated

### 2.4 DegradationTier

```
DegradationTier:
  tier_id:          string           // e.g. "T0", "T1", "T2"
  required:         Map<dim, threshold>  // capabilities needed for this tier
  quality_estimate: float ∈ (0, 1]  // estimated output quality at this tier
  description:      string           // human-readable: what this tier produces
```

**Invariants:**
- Tiers are ordered by quality_estimate descending: T0 > T1 > T2 > ...
- T0 must have quality_estimate equal to the highest achievable (often 1.0)
- The lowest tier must have quality_estimate ≥ q_min_j
- Every tier's `required` map must be a subset of (R_j^req ∪ R_j^pref)
- Higher tiers are strict supersets capability-wise: if Tk requires dim d, then all T0..T(k-1) also require d (or a stronger threshold on d)

**Limitations: Linear Tiers vs. DAGs**
The linear structure (T0 > T1 > T2) assumes that degradation pathways are strictly sequential. However, some tasks might have branching degradation paths (e.g., if you lose Lidar, you can fallback to either Stereo Vision OR Monocular Vision, but these aren't strictly better/worse than each other, they are just different DAG branches). 
In v0.1, HESK forces a linear projection: the mission designer must decide which branch is arbitrarily "better" (e.g., Stereo Vision = T1, Monocular = T2) to fit the 1D degradation model. True Directed Acyclic Graph (DAG) based degradation paths are deferred to future versions due to the complexity they add to the state machine and conflict resolution.

### 2.5 DataFlowRequirement

```
DataFlowRequirement:
  source_capability: string      // producing capability dimension, e.g. "sensing.rgb"
  sink_capability:   string      // consuming capability dimension, e.g. "compute.gpu"
  bandwidth_kbps:    float       // minimum sustained bandwidth required
  max_latency_ms:    float       // maximum acceptable one-way latency
  description:       string      // e.g. "camera frames to GPU for SLAM"
```

Data flows define the **communication edges** within a task's execution graph. For a single-node executor, all flows are internal (trivially satisfied). For a coalition, each flow maps to an inter-node communication link whose feasibility must be verified (see 005, Invariant 9).

### 2.6 TaskLifecycleState

```
TaskLifecycleState:
  PENDING              // task exists in a mission plan, not yet announced
  ANNOUNCED            // task broadcast to reachable nodes for bidding
  BIDDING              // bids being collected, evaluation window open
  ASSIGNED             // winning bidder selected, execution not yet started
  EXECUTING            // active work in progress
  COMPLETED            // successfully finished, results available
  FAILED               // execution attempted, unrecoverable failure
  DEGRADED             // executing at reduced quality tier
  ABANDONED            // deliberately dropped (resource scarcity, priority shed)
```

Terminal states: COMPLETED, FAILED, ABANDONED.

Non-terminal states: PENDING, ANNOUNCED, BIDDING, ASSIGNED, EXECUTING, DEGRADED.

### 2.7 TaskRecord

The full runtime representation of a task, combining its static requirement with dynamic state:

```
TaskRecord:
  requirement:        TaskRequirement
  lifecycle_state:    TaskLifecycleState
  current_tier:       DegradationTier | null     // which tier is active (if executing/degraded)
  assigned_to:        node_id | coalition_id | null
  bid_window_end:     Timestamp | null           // when bidding closes
  execution_start:    Timestamp | null
  state_history:      [(state, timestamp, λ, trigger_event)]
  last_updated:       (node_id, λ)               // provenance of latest state change
```

---

## 3. ASSUMPTIONS

1. **Task requirements are defined at mission planning time.** A human mission designer or a mission-planning module creates TaskRequirement structures before or at mission start. Nodes do not invent task requirements autonomously in v0.1.

2. **Degradation tiers are defined by the mission designer.** The tier structure (how many tiers, what each requires, quality estimates) is part of the mission specification. Nodes do not auto-generate tiers. This is a deliberate design choice: the mission designer understands the operational semantics of "what constitutes acceptable degraded mapping" better than runtime heuristics.

3. **Tasks are independent in v0.1.** No task-to-task dependencies (e.g., "scan zone A before mapping zone B"). Temporal ordering and DAG dependencies are deferred to future versions (see §14).

4. **Priority values are globally consistent.** All nodes that receive a task announcement receive the same π_j. Priority is not locally modifiable in v0.1.

5. **Capability dimension names are globally agreed.** All nodes share the same capability vocabulary (defined in 001). A node advertising `sensing.rgb` means the same thing as a task requiring `sensing.rgb`.

6. **Quality estimates are designer-provided approximations.** The quality_estimate on a DegradationTier is a pre-mission human judgment, not a runtime measurement. Actual quality may differ; this is acceptable for v0.1.

7. **Deadlines, when specified, reference elapsed time from execution start**, not wall-clock instants. This avoids clock synchronization requirements across nodes.

8. **A task may be assigned to exactly one executor** (a single node or a single coalition) at a time. Concurrent duplicate execution is not supported in v0.1.

---

## 4. INPUTS

The Task Model receives input from three sources:

### 4.1 Mission Specification (pre-mission)

```
Input: mission_spec
  tasks:  [TaskDefinition]   // human-designed task definitions
    each TaskDefinition contains:
      task_id, description
      required: Map<dim, threshold>
      preferred: Map<dim, threshold>
      priority: float
      min_quality: float
      degradation_tiers: [TierDefinition]
      data_flows: [DataFlowDefinition]
      deadline: Duration | null
      spatial_constraint: SpatialConstraint | null
```

### 4.2 Lifecycle Events (runtime)

```
Input: lifecycle_event
  event_type: ANNOUNCE | BID_RECEIVED | BID_TIMEOUT | ASSIGN |
              EXECUTION_START | EXECUTION_COMPLETE | EXECUTION_FAIL |
              TIER_DOWNGRADE | TIER_UPGRADE | ABANDON | REASSIGN_TRIGGER
  task_id:    string
  source:     node_id
  timestamp:  λ (Lamport clock value)
  payload:    event-specific data
```

### 4.3 Task Announcements (received from other nodes)

```
Input: task_announcement_msg
  task_requirement: TaskRequirement   // full requirement structure
  sender:           node_id
  sender_clock:     λ
  announcement_id:  string            // unique per announcement
```

---

## 5. LOCALLY AVAILABLE INFORMATION

Following the Construction Guide's observability discipline, we classify what a node n_i *actually has access to* when making task-related decisions:

### KNOWN (ground truth available locally)

- **Own mission plan:** Tasks loaded from n_i's mission specification at startup
- **Own lifecycle state:** Current TaskLifecycleState for tasks n_i owns or is assigned to
- **Own state history:** Complete (state, timestamp, λ, event) log for locally tracked tasks
- **Own Lamport clock:** λ_i, monotonically incrementing
- **Own capability state:** C_i (from 001), enabling n_i to evaluate whether it satisfies R_j^req

### RECEIVED (from messages, with provenance)

- **Announced tasks from other nodes:** TaskRequirement structures received via task_announcement_msg. Each carries (sender_id, sender_λ). Node n_i knows these tasks exist and their requirements, but does *not* know:
  - Whether other nodes also received the announcement
  - Whether the announcing node is still alive
  - What bids other nodes have submitted
- **Lifecycle updates from assignees:** State transition notifications (e.g., "task τ_j is now EXECUTING on n_k") received from other nodes, tagged with (source_id, source_λ)
- **Bid submissions:** If n_i is managing a bidding round, it receives bids with (bidder_id, bidder_λ, bid_payload)

### INFERRED (derived from local reasoning)

- **Task feasibility for self:** Whether C_i satisfies R_j^req, and at which DegradationTier
- **Task quality estimate for self:** Which tier n_i could execute at, given C_i
- **Staleness of received task state:** Elapsed time since last update on a task from another node

### UNKNOWN (not accessible, must not be assumed)

- **All tasks in the swarm:** Node n_i does NOT have a global task registry. It only knows tasks from its own mission plan + received announcements
- **Bids submitted by other nodes** (unless explicitly forwarded)
- **Current lifecycle state of tasks managed by other nodes** (unless updates received)
- **Whether an announced task has been assigned elsewhere**
- **True global priority ordering across all swarm tasks**
- **Real-time capability state of other nodes** (only last-received snapshots)

This separation is fundamental. Any algorithm that reads from the UNKNOWN category violates Invariants 1, 2, and 10.

---

## 6. OUTPUT

The Task Model produces the following outputs consumed by downstream algorithms:

### 6.1 TaskRequirement (constructed)

```
construct_task_requirement(task_def: TaskDefinition) → TaskRequirement
```

A fully validated, structured task requirement ready for announcement, matching, and degradation reasoning.

### 6.2 DegradationTier list (defined)

```
define_degradation_tiers(full_req: TaskRequirement) → [DegradationTier]
```

An ordered list of fallback tiers, each specifying a reduced capability set and estimated quality. Consumed directly by 006_graceful_degradation.

### 6.3 Lifecycle state transitions

```
advance_lifecycle(current_state: TaskLifecycleState, event: LifecycleEvent) → TaskLifecycleState
```

A new lifecycle state, or rejection if the transition is invalid. State changes are recorded in the task's state_history and propagated to relevant nodes.

### 6.4 Validation results

```
validate_task_requirement(req: TaskRequirement) → (valid: bool, errors: [string])
```

Structural and semantic validation of a TaskRequirement, catching malformed inputs before they enter the system.

---

## 7. DECISION RULE — Task Lifecycle State Machine

The lifecycle state machine governs all legal task state transitions. This is the primary "decision rule" of the Task Model — determining **what transitions are permitted**, **under what conditions**, and **who may trigger them**.

### 7.1 State Transition Diagram

```
                            ┌──────────────────────────────┐
                            │          ABANDONED           │
                            └──────────────────────────────┘
                                          ▲
                    (from ANY non-terminal state)
                                          │
  ┌─────────┐     ┌───────────┐     ┌──────────┐     ┌──────────┐     ┌───────────┐
  │ PENDING  │────▶│ ANNOUNCED │────▶│ BIDDING  │────▶│ ASSIGNED │────▶│ EXECUTING │
  └─────────┘     └───────────┘     └──────────┘     └──────────┘     └───────────┘
                                         ▲  │              │               │  │  │
                                         │  │              │               │  │  │
                                         │  └──────────────┘               │  │  │
                                         │   (reassign:                    │  │  │
                                         │    ASSIGNED→BIDDING)            │  │  │
                                         │                                 │  │  │
                                         │         ┌───────────┐           │  │  │
                                         │         │ DEGRADED  │◀──────────┘  │  │
                                         │         └───────────┘              │  │
                                         │              │  ▲                  │  │
                                         │              │  │                  │  │
                                         │              │  └──────────────────┘  │
                                         │              │   (tier upgrade:       │
                                         │              │    EXECUTING→DEGRADED  │
                                         │              │    or DEGRADED→EXEC.)  │
                                         │              │                        │
                                         │              ▼                        ▼
                                    ┌──────────┐  ┌──────────┐          ┌───────────┐
                                    │  FAILED  │  │COMPLETED │          │  FAILED   │
                                    └──────────┘  └──────────┘          └───────────┘
```

### 7.2 Complete Transition Table

| # | From | To | Triggering Event | Preconditions |
|---|------|----|-----------------|---------------|
| T1 | PENDING | ANNOUNCED | ANNOUNCE | Task passes `validate_task_requirement`. Announcing node has the task in its mission plan or created it from local perception. |
| T2 | ANNOUNCED | BIDDING | BID_WINDOW_OPEN | At least one reachable node exists (local knowledge). Bid window duration set. |
| T3 | BIDDING | ASSIGNED | BID_ACCEPTED | Bid evaluation complete. Winning bidder selected. Bidder capability check passed at time of selection. Winner acknowledged (or timeout-with-default). |
| T4 | ASSIGNED | EXECUTING | EXECUTION_START | Assigned node/coalition confirms readiness. Capability re-check: assignee still satisfies at least lowest acceptable tier. |
| T5 | EXECUTING | COMPLETED | EXECUTION_COMPLETE | Executor reports successful completion. Results available (if applicable). Quality ≥ q_min_j. |
| T6 | EXECUTING | FAILED | EXECUTION_FAIL | Unrecoverable error. Executor capability dropped below all tier minimums OR executor node lost OR deadline exceeded. |
| T7 | EXECUTING | DEGRADED | TIER_DOWNGRADE | Executor capability dropped below current tier threshold but still satisfies a lower tier with quality ≥ q_min_j. New tier assigned. |
| T8 | DEGRADED | EXECUTING | TIER_UPGRADE | Executor capability recovered sufficiently for a higher tier. Current tier updated. (Note: state returns to EXECUTING with a new current_tier, representing improved operation.) |
| T9 | DEGRADED | COMPLETED | EXECUTION_COMPLETE | Degraded execution finished successfully. Quality ≥ q_min_j at degraded tier. |
| T10 | DEGRADED | FAILED | EXECUTION_FAIL | Capability dropped below all tiers OR executor lost OR deadline exceeded. |
| T11 | ASSIGNED | BIDDING | REASSIGN_TRIGGER | Assigned node reports inability, becomes unreachable (suspected), or explicitly declines. Task requirement unchanged; new bidding round opens. |
| T12 | ANY non-terminal | ABANDONED | ABANDON | Resource scarcity forces priority shedding (006). Task priority_class permits abandonment (usually OPTIONAL first). OR mission controller explicitly abandons. |

**Transition T8 semantics:** DEGRADED → EXECUTING represents a quality tier upgrade. The task was running at a lower tier (DEGRADED state) and the executor's capabilities recovered (e.g., GPU offload became available, link quality improved). The task returns to EXECUTING at the higher tier. The distinction: EXECUTING means "running at or above the initially assigned tier" while DEGRADED means "running below the initially assigned tier." Both are active execution states.

### 7.3 Transition Validation Rule

```
advance_lifecycle(current_state, event) → new_state:
  transition = lookup(current_state, event) in transition_table
  IF transition is null:
    RETURN (current_state, error: "invalid transition")
  IF NOT all preconditions of transition are met:
    RETURN (current_state, error: "precondition failed: <detail>")
  new_state = transition.to_state
  record (current_state → new_state, event, λ_i, wall_time) in state_history
  λ_i = λ_i + 1
  RETURN (new_state, ok)
```

---

## 8. PLAIN-ENGLISH ALGORITHM

### 8.1 Task Requirement Construction

1. Mission designer provides a task definition with required capabilities, preferred capabilities, priority, minimum quality, degradation tiers, and data flows.
2. System validates the definition: required ∩ preferred = ∅; tiers are ordered by quality; lowest tier quality ≥ min_quality; data flow source/sink capabilities exist in (required ∪ preferred); priority ∈ (0,1].
3. System derives priority_class from π_j (CRITICAL if ≥0.80, IMPORTANT if ≥0.40, OPTIONAL otherwise).
4. System assigns provenance: (creator_node_id, λ_creator), version = 1.
5. TaskRequirement is stored in local ledger.

### 8.2 Degradation Tier Definition

1. Mission designer specifies ordered tiers from highest quality (T0 = full capability) to lowest acceptable (Tn).
2. Each tier lists *only the capabilities required for that tier's operation*, drawn from R_j^req ∪ R_j^pref.
3. System validates: T0 quality > T1 quality > ... > Tn quality ≥ q_min_j.
4. System validates: each Tk's required set is a subset of T(k-1)'s required set (higher tiers need *at least as much* as lower tiers).
5. Tiers are attached to the TaskRequirement.

### 8.3 Task Announcement

1. When a node decides a task should be executed (e.g., mission plan says "start mapping at T=60s"), it transitions the task PENDING → ANNOUNCED.
2. The node broadcasts a task_announcement_msg containing the full TaskRequirement to all reachable neighbors.
3. Receiving nodes store the TaskRequirement in their local ledger (with provenance) and may evaluate whether they can bid.

### 8.4 Lifecycle Advancement

1. On any lifecycle event, the owning node looks up the valid transition in the transition table (§7.2).
2. If the transition is valid and preconditions are met, the state advances.
3. The state change is recorded in state_history with Lamport timestamp.
4. Relevant nodes are notified (the assignee, bidders, neighbors tracking this task).

### 8.5 Data Flow Validation (for coalition feasibility)

1. For each DataFlowRequirement in the task, identify which coalition member provides the source_capability and which provides the sink_capability.
2. Verify that the communication link between those two members meets bandwidth_kbps and max_latency_ms.
3. If *any* data flow is infeasible, the coalition cannot execute the task. This check is consumed by 005_coalition_formation but defined here in the task model because data flows are a property of the *task*, not the *coalition*.

---

## 9. PSEUDOCODE

### 9.1 construct_task_requirement

```
FUNCTION construct_task_requirement(task_def, creator_node_id, λ) → TaskRequirement:
  // Derive priority class
  IF task_def.priority >= 0.80:
    priority_class = CRITICAL
  ELSE IF task_def.priority >= 0.40:
    priority_class = IMPORTANT
  ELSE:
    priority_class = OPTIONAL

  req = TaskRequirement {
    task_id:           task_def.task_id,
    description:       task_def.description,
    required:          task_def.required,
    preferred:         task_def.preferred,
    priority:          task_def.priority,
    priority_class:    priority_class,
    min_quality:       task_def.min_quality,
    degradation_tiers: task_def.degradation_tiers,  // validated below
    data_flows:        task_def.data_flows,
    deadline:          task_def.deadline,
    spatial_constraint: task_def.spatial_constraint,
    created_at:        (creator_node_id, λ),
    version:           1
  }

  (valid, errors) = validate_task_requirement(req)
  IF NOT valid:
    RAISE ValidationError(errors)

  RETURN req
```

### 9.2 validate_task_requirement

```
FUNCTION validate_task_requirement(req) → (valid: bool, errors: [string]):
  errors = []

  // 1. Priority range
  IF req.priority <= 0 OR req.priority > 1:
    errors.append("priority must be in (0, 1]")

  // 2. Min quality range
  IF req.min_quality <= 0 OR req.min_quality > 1:
    errors.append("min_quality must be in (0, 1]")

  // 3. Required ∩ preferred must be empty
  overlap = keys(req.required) ∩ keys(req.preferred)
  IF overlap ≠ ∅:
    errors.append("dimensions in both required and preferred: " + overlap)

  // 4. Degradation tier ordering
  FOR i = 0 TO len(req.degradation_tiers) - 2:
    IF req.degradation_tiers[i].quality_estimate <= req.degradation_tiers[i+1].quality_estimate:
      errors.append("tiers not strictly descending at index " + i)

  // 5. Lowest tier quality ≥ min_quality
  IF len(req.degradation_tiers) > 0:
    lowest = req.degradation_tiers[LAST]
    IF lowest.quality_estimate < req.min_quality:
      errors.append("lowest tier quality " + lowest.quality_estimate +
                     " < min_quality " + req.min_quality)

  // 6. Tier capability subset chain
  FOR i = 1 TO len(req.degradation_tiers) - 1:
    higher_dims = keys(req.degradation_tiers[i-1].required)
    this_dims   = keys(req.degradation_tiers[i].required)
    IF NOT this_dims ⊆ higher_dims:
      extra = this_dims - higher_dims
      errors.append("tier " + i + " requires dimensions not in higher tier: " + extra)

  // 7. Data flow source/sink must exist in required ∪ preferred
  all_dims = keys(req.required) ∪ keys(req.preferred)
  FOR flow IN req.data_flows:
    IF flow.source_capability NOT IN all_dims:
      errors.append("data flow source '" + flow.source_capability + "' not in task capabilities")
    IF flow.sink_capability NOT IN all_dims:
      errors.append("data flow sink '" + flow.sink_capability + "' not in task capabilities")

  // 8. Data flow bandwidth and latency positive
  FOR flow IN req.data_flows:
    IF flow.bandwidth_kbps <= 0:
      errors.append("data flow bandwidth must be positive")
    IF flow.max_latency_ms <= 0:
      errors.append("data flow max_latency must be positive")

  // 9. At least one degradation tier
  IF len(req.degradation_tiers) == 0:
    errors.append("at least one degradation tier required")

  RETURN (len(errors) == 0, errors)
```

### 9.3 define_degradation_tiers

```
FUNCTION define_degradation_tiers(tier_defs: [TierDefinition]) → [DegradationTier]:
  // tier_defs comes from mission designer, already ordered T0 first
  tiers = []
  FOR i, td IN enumerate(tier_defs):
    tier = DegradationTier {
      tier_id:          "T" + str(i),
      required:         td.required,
      quality_estimate: td.quality_estimate,
      description:      td.description
    }
    tiers.append(tier)

  // Validation is handled by validate_task_requirement
  RETURN tiers
```

### 9.4 advance_lifecycle

```
FUNCTION advance_lifecycle(record: TaskRecord, event: LifecycleEvent, λ_i) → (TaskRecord, Result):
  current = record.lifecycle_state

  // Check terminal states
  IF current IN {COMPLETED, FAILED, ABANDONED}:
    RETURN (record, Error("task in terminal state: " + current))

  // Transition table lookup
  new_state = NULL
  MATCH (current, event.event_type):
    (PENDING,    ANNOUNCE)            → new_state = ANNOUNCED
    (ANNOUNCED,  BID_WINDOW_OPEN)     → new_state = BIDDING
    (BIDDING,    BID_ACCEPTED)        → new_state = ASSIGNED
    (ASSIGNED,   EXECUTION_START)     → new_state = EXECUTING
    (EXECUTING,  EXECUTION_COMPLETE)  → new_state = COMPLETED
    (EXECUTING,  EXECUTION_FAIL)      → new_state = FAILED
    (EXECUTING,  TIER_DOWNGRADE)      → new_state = DEGRADED
    (DEGRADED,   TIER_UPGRADE)        → new_state = EXECUTING
    (DEGRADED,   EXECUTION_COMPLETE)  → new_state = COMPLETED
    (DEGRADED,   EXECUTION_FAIL)      → new_state = FAILED
    (ASSIGNED,   REASSIGN_TRIGGER)    → new_state = BIDDING
    (_,          ABANDON)             → new_state = ABANDONED
    _                                 → RETURN (record, Error("no valid transition"))

  // Precondition checks (event-specific)
  precondition_result = check_preconditions(current, new_state, event, record)
  IF precondition_result.failed:
    RETURN (record, Error("precondition: " + precondition_result.reason))

  // Apply transition
  record.lifecycle_state = new_state
  record.state_history.append((current, new_state, λ_i, event))
  record.last_updated = (event.source, λ_i)

  // State-specific updates
  IF new_state == ASSIGNED:
    record.assigned_to = event.payload.winner_id
  IF new_state == EXECUTING AND current == ASSIGNED:
    record.execution_start = wall_time()
    record.current_tier = record.requirement.degradation_tiers[0]  // start at T0
  IF new_state == DEGRADED:
    record.current_tier = event.payload.new_tier
  IF new_state == EXECUTING AND current == DEGRADED:
    record.current_tier = event.payload.new_tier  // upgraded tier
  IF new_state == BIDDING AND current == ASSIGNED:
    record.assigned_to = NULL
    record.bid_window_end = wall_time() + BID_WINDOW_DURATION

  RETURN (record, Ok)
```

### 9.5 find_best_tier (utility for matching/degradation)

```
FUNCTION find_best_tier(capability_state: C_i, task_req: TaskRequirement) → DegradationTier | NULL:
  // Returns the highest-quality tier that C_i can satisfy
  // Used by 003_capability_matching and 006_graceful_degradation

  FOR tier IN task_req.degradation_tiers:   // T0 first (highest quality)
    satisfies = TRUE
    FOR (dim, threshold) IN tier.required:
      IF NOT capability_satisfies(C_i, dim, threshold):   // defined in 001
        satisfies = FALSE
        BREAK
    IF satisfies:
      RETURN tier

  RETURN NULL   // cannot satisfy any tier
```

---

## 10. WORKED EXAMPLE

### Task: `mapping_zone_b`

**Mission specification input:**

```
task_def = {
  task_id:     "mapping_zone_b",
  description: "Produce spatial map of zone B for navigation",
  required:    { localization: 0.7, sensing.rgb: 0.6 },
  preferred:   { sensing.lidar: 0.8, compute.gpu: 0.5 },
  priority:    0.91,
  min_quality: 0.40,
  degradation_tiers: [
    { required: { localization: 0.7, sensing.rgb: 0.6, sensing.lidar: 0.8, compute.gpu: 0.5 },
      quality_estimate: 1.0,
      description: "Full 3D mapping — lidar point cloud + visual SLAM + GPU processing" },
    { required: { localization: 0.7, sensing.rgb: 0.6, compute.gpu: 0.5 },
      quality_estimate: 0.70,
      description: "Dense visual mapping — camera-based SLAM + GPU, no lidar" },
    { required: { localization: 0.7, sensing.rgb: 0.6 },
      quality_estimate: 0.40,
      description: "Sparse landmark mapping — camera landmarks only, no GPU acceleration" }
  ],
  data_flows: [
    { source_capability: "sensing.rgb", sink_capability: "compute.gpu",
      bandwidth_kbps: 5000, max_latency_ms: 100,
      description: "Camera frames to GPU for visual SLAM" },
    { source_capability: "compute.gpu", sink_capability: "output.map",
      bandwidth_kbps: 100, max_latency_ms: 500,
      description: "Processed map tiles to map output store" }
  ],
  deadline: Duration(600s),
  spatial_constraint: { zone: "B", type: "coverage" }
}
```

### Step 1: Construction

```
req = construct_task_requirement(task_def, creator_node_id="n_1", λ=42)

Result:
  task_id:        "mapping_zone_b"
  priority:       0.91
  priority_class: CRITICAL   (0.91 ≥ 0.80)
  min_quality:    0.40
  created_at:     (n_1, 42)
  version:        1
```

### Step 2: Validation

```
validate_task_requirement(req) → (true, [])

Checks passed:
  ✓ priority 0.91 ∈ (0, 1]
  ✓ min_quality 0.40 ∈ (0, 1]
  ✓ required ∩ preferred = ∅
    required dims: {localization, sensing.rgb}
    preferred dims: {sensing.lidar, compute.gpu}
  ✓ tier ordering: 1.0 > 0.70 > 0.40
  ✓ lowest tier quality 0.40 ≥ min_quality 0.40
  ✓ tier subset chain:
    T0 dims: {localization, sensing.rgb, sensing.lidar, compute.gpu}
    T1 dims: {localization, sensing.rgb, compute.gpu} ⊆ T0 ✓
    T2 dims: {localization, sensing.rgb} ⊆ T1 ✓
  ✓ data flow sources/sinks in required ∪ preferred
    sensing.rgb ∈ required ✓
    compute.gpu ∈ preferred ✓
    output.map — NOTE: not in required or preferred
```

**Design decision exposed:** `output.map` appears as a data flow sink but is not in required or preferred. This reveals that data flow endpoints may reference *output* capabilities that are implicit. 

> **Provisional choice:** Data flow sinks may reference capability dimensions not in required/preferred if they represent output channels rather than input capabilities. Validation relaxed for sink capabilities with prefix `output.`. This is flagged in §14 as an open question.

### Step 3: Degradation Tier Interpretation

```
Tier T0 ("Full 3D mapping"):
  Requires: localization ≥ 0.7, sensing.rgb ≥ 0.6, sensing.lidar ≥ 0.8, compute.gpu ≥ 0.5
  Quality:  1.00
  → Best possible output. Needs a node (or coalition) with all four capabilities.

Tier T1 ("Dense visual mapping"):
  Requires: localization ≥ 0.7, sensing.rgb ≥ 0.6, compute.gpu ≥ 0.5
  Quality:  0.70
  → Drops lidar. Camera-based SLAM only. Usable for navigation but less precise.

Tier T2 ("Sparse landmark mapping"):
  Requires: localization ≥ 0.7, sensing.rgb ≥ 0.6
  Quality:  0.40
  → Camera landmarks only. Minimal but meets min_quality threshold.
  → Below this, the task cannot produce useful output → FAILED or ABANDONED.
```

### Step 4: Lifecycle Trace

```
Time  Event                           State Transition      Notes
─────────────────────────────────────────────────────────────────────────
T=0   Mission loaded on n_1           PENDING               Task in n_1's local plan
T=60  n_1 announces mapping_zone_b    PENDING → ANNOUNCED   Broadcast to n_2, n_3, n_4
T=61  Bid window opens                ANNOUNCED → BIDDING   30s bid window
T=63  n_2 bids (can do T0)            (bid recorded)        n_2 has lidar+gpu+camera
T=65  n_3 bids (can do T1)            (bid recorded)        n_3 has camera+gpu, no lidar
T=91  Bid window closes, n_2 wins     BIDDING → ASSIGNED    Best tier capability
T=93  n_2 confirms, starts            ASSIGNED → EXECUTING  current_tier = T0
T=250 n_2 lidar sensor degrades       EXECUTING → DEGRADED  Drops to T1 (q=0.70)
T=400 n_2 GPU recovers (offload)      DEGRADED → EXECUTING  Back to T0 (q=1.00)
T=580 Mapping complete                EXECUTING → COMPLETED Results stored
```

### Step 5: Data Flow in Coalition Scenario

If no single node can do T0, a coalition might form:

```
Coalition Γ = {n_3 (camera + localization), n_5 (GPU)}

Data flow check:
  Flow 1: sensing.rgb (n_3) → compute.gpu (n_5)
    Required: 5000 kbps, ≤ 100ms latency
    Link n_3 ↔ n_5: measured 8200 kbps, 45ms → FEASIBLE ✓

  Flow 2: compute.gpu (n_5) → output.map (n_5, local)
    Required: 100 kbps, ≤ 500ms
    Internal to n_5 → TRIVIALLY FEASIBLE ✓

Coalition can execute at T1 (no lidar available).
```

---

## 11. EDGE CASES

### 11.1 Task with no preferred capabilities

```
required: { sensing.thermal: 0.9 }
preferred: {}
```

Valid. All tiers will reference only required dimensions. Only one meaningful tier possible (T0 = full, quality 1.0). Effectively a binary pass/fail task with a quality floor.

### 11.2 Task where min_quality equals T0 quality

```
min_quality: 1.0
degradation_tiers: [T0(q=1.0)]
```

Valid but rigid. No degradation possible. If T0 cannot be satisfied, the task goes directly to FAILED or ABANDONED — no graceful degradation. This is the degenerate case equivalent to the naive binary model.

### 11.3 All reachable nodes can only satisfy the lowest tier

Every bidder satisfies T2 only. The task executes at T2 (DEGRADED state from the start). This is acceptable as long as T2 quality ≥ q_min_j.

### 11.4 No reachable node can satisfy any tier

No bids received during the bid window. The task remains in BIDDING until timeout, then either:
- **Option A:** Returns to ANNOUNCED for periodic re-announcement (awaiting new nodes or capability recovery). Provisional choice for v0.1.
- **Option B:** Transitions to ABANDONED if priority_class is OPTIONAL.
- **Option C:** Remains BIDDING indefinitely for CRITICAL tasks.

> **Provisional choice:** BIDDING → ANNOUNCED on bid timeout for CRITICAL/IMPORTANT tasks (re-announce after backoff). BIDDING → ABANDONED on bid timeout for OPTIONAL tasks.

### 11.5 Assigned node becomes unreachable before execution starts

ASSIGNED → BIDDING via REASSIGN_TRIGGER. The task re-enters the bidding phase. If the node later returns and claims the assignment, reconciliation (008) must resolve the conflict.

### 11.6 Executor capability degrades below all tiers during execution

EXECUTING (or DEGRADED) → FAILED. The task cannot produce output meeting q_min_j. Downstream systems (006) decide whether to re-announce or abandon.

### 11.7 Duplicate task announcements after partition

Node n_1 announces τ_j. Partition occurs. Node n_1 announces τ_j again (new announcement_id, same task_id). Receiving nodes deduplicate by task_id + version. If version is identical, ignore. If version is higher, update local copy.

### 11.8 Empty data_flows

Valid. Some tasks have no inter-capability data dependencies (e.g., a simple sensing task where one node captures and stores locally). Coalition formation for such tasks only checks capability coverage, not communication feasibility.

### 11.9 Deadline expiration during BIDDING

If the deadline is specified relative to execution start, it does not apply during BIDDING. However, a separate *bid_window_timeout* controls how long bidding lasts. If a task has been in BIDDING through multiple failed rounds for an extended period, this is a mission-level concern handled by priority shedding (006), not the lifecycle machine itself.

---

## 12. FAILURE MODES

### 12.1 Malformed task requirement from mission spec

**Symptom:** `validate_task_requirement` returns errors.  
**Cause:** Mission designer error — e.g., overlapping required/preferred, non-descending tiers, missing tiers.  
**Mitigation:** Validation at construction time. Task is rejected before entering the system. Clear error messages guide correction.

### 12.2 Priority inversion under scarcity

**Symptom:** A CRITICAL task is starved while an IMPORTANT task consumes the only capable node.  
**Cause:** Task assignment does not preempt. In v0.1, once assigned, a task holds its executor.  
**Mitigation:** Degradation engine (006) can trigger REASSIGN for lower-priority tasks to free executors. Preemption semantics are deferred (see §14).

### 12.3 Stale lifecycle state after partition

**Symptom:** Node n_i believes τ_j is BIDDING; node n_k believes τ_j is EXECUTING.  
**Cause:** Lifecycle update message lost during partition.  
**Mitigation:** State carries provenance (node_id, λ). On reconnection, reconciliation (008) compares state histories. The more advanced state with valid causal chain takes precedence.

### 12.4 Bid window too short — no bids received

**Symptom:** BIDDING → timeout with zero bids. Task cycles through ANNOUNCED → BIDDING → ANNOUNCED.  
**Mitigation:** Exponential backoff on re-announcement. After N failed rounds, escalate: if OPTIONAL, abandon; if CRITICAL, alert (log to local ledger for human review).

### 12.5 Data flow requirement infeasible for all possible coalitions

**Symptom:** Task requires 5000 kbps between camera and GPU, but no inter-node link exceeds 2000 kbps.  
**Cause:** Task data flow requirements exceed network capacity.  
**Mitigation:** If a single node with both capabilities exists, the task can still execute (internal data flow). Otherwise, the task degrades to a tier that doesn't require the infeasible data flow, or fails.

### 12.6 Degradation tier quality estimates are inaccurate

**Symptom:** Task executes at T1 (estimated q=0.70) but actual output quality is 0.30 (below q_min_j).  
**Cause:** Designer's quality estimate was optimistic.  
**Mitigation:** v0.1 treats quality_estimate as advisory. Runtime quality measurement is out of scope. Future versions may validate actual output quality and trigger FAILED if below q_min_j.

---

## 13. INVARIANTS

The following properties must hold at all times within the Task Model:

### I-T1: Capability separation
Task requirements specify *what capabilities are needed*, never *which node should execute*. No TaskRequirement references a specific node_id. (Architectural Invariant 5: task responsibility and physical capability are separate.)

### I-T2: Local-only lifecycle transitions
A node may only advance the lifecycle of tasks it is authoritative over — tasks it announced, tasks it is assigned to execute, or tasks it is managing a bid round for. No node remotely forces a lifecycle transition on another node's task. (Architectural Invariant 2.)

### I-T3: Provenance on all state
Every TaskRecord carries (node_id, λ) provenance on creation and last_updated. Every state_history entry carries a Lamport timestamp. No task state exists without attribution. (Architectural Invariant 6.)

### I-T4: Degradation tier monotonicity
quality_estimate strictly decreases across tiers: T0 > T1 > ... > Tn. This is validated at construction time and never modified at runtime.

### I-T5: Minimum quality floor
No tier may have quality_estimate < q_min_j. Execution at quality below q_min_j is treated as FAILED, not DEGRADED.

### I-T6: Terminal state finality
Once a task enters COMPLETED, FAILED, or ABANDONED, it does not transition to any other state. A new task (new task_id) must be created if re-execution is desired.

### I-T7: No global task registry
No node possesses a complete list of all tasks in the swarm. Each node's task knowledge is limited to its own mission plan + received announcements. (Architectural Invariants 1, 2.)

### I-T8: Priority immutability (v0.1)
π_j is set at mission planning time and does not change during execution. Priority re-weighting under dynamic conditions is deferred.

### I-T9: Data flows are task properties
DataFlowRequirements are defined by the task, not by the coalition or the network. They represent *what the task needs*, not *what the network provides*. Feasibility checking is performed against the network but the requirements themselves are static.

---

## 14. OPEN QUESTIONS

### Q1: Who defines degradation tiers?

**Options:**
- **(A) Mission designer only.** Tiers are part of the mission specification. The designer understands operational semantics (e.g., what "sparse landmark mapping" means for navigation quality).
- **(B) Automatic generation from required/preferred split.** System generates tiers by progressively dropping preferred dimensions. Simpler, but quality_estimate must be auto-calculated (unreliable).
- **(C) Hybrid.** Designer specifies key tiers; system interpolates intermediate tiers.

**Tradeoffs:** (A) produces the most meaningful tiers but requires mission design effort for every task. (B) is low-effort but may produce operationally meaningless tiers (e.g., dropping lidar but keeping GPU when GPU without lidar has no purpose).

**Provisional choice:** (A) for v0.1. The number of task types in early experiments is small enough for manual tier definition.

### Q2: Temporal dependencies between tasks

**Problem:** "Scan zone A before mapping zone A" requires task ordering that v0.1 does not support.

**Options:**
- **(A) Explicit DAG in mission spec.** Tasks declare `depends_on: [task_id]`. PENDING → ANNOUNCED transition gated on dependency completion.
- **(B) Implicit through spatial/temporal constraints.** Tasks have time windows that encode ordering indirectly.
- **(C) Deferred.** All tasks are independent in v0.1.

**Provisional choice:** (C). DAG dependencies add complexity to lifecycle management (what happens when a dependency FAILS? Does the dependent task ABANDON or wait?) that should be addressed after core allocation works.

### Q3: Periodic / recurring tasks

**Problem:** "Patrol zone C every 300 seconds" is a recurring task. The current model treats each task instance as unique.

**Options:**
- **(A) Task generator.** A meta-task spawns new task instances on a schedule.
- **(B) Lifecycle loop.** COMPLETED → PENDING for recurring tasks.

**Provisional choice:** (A). Lifecycle loop violates I-T6 (terminal state finality). A generator creating fresh task instances is cleaner.

### Q4: Node-type eligibility vs. capability thresholds

**Problem:** Should a task be able to say "only drones, not rovers" in addition to capability thresholds?

**Options:**
- **(A) Never.** If capabilities are well-modeled, node type is redundant. A rover with sufficient mobility should be eligible for a "fly-over" task if it can reach the area.
- **(B) Soft preference.** `preferred_platform_type: aerial` adds a small bonus to match score but doesn't exclude.
- **(C) Hard filter.** `eligible_types: [aerial]` excludes ground vehicles.

**Tradeoffs:** (A) is the purest capability-driven approach but may fail for physics-constrained tasks (e.g., aerial photography). (C) re-introduces the rigidity HESK aims to avoid.

**Provisional choice:** (A) for v0.1. If a task requires capabilities that only aerial platforms have (e.g., `mobility.flight: 1.0`), the capability model already filters. Explicit type filters are unnecessary and violate the spirit of capability-driven allocation.

### Q5: Priority conflicts and dynamic re-prioritization

**Problem:** Two CRITICAL tasks compete for the same scarce resource. Current model has static priorities with no runtime adjustment.

**Options:**
- **(A) Static priority + first-come-first-served within class.** Simple, deterministic, potentially suboptimal.
- **(B) Mission controller can issue REPRIORITIZE events.** Adds a new lifecycle event and violates I-T8.
- **(C) Context-dependent priority modifiers.** Priority increases as deadline approaches or as partial results accumulate.

**Provisional choice:** (A) for v0.1. Fine-grained priority is the exact numeric π_j value, which provides ordering within a class. Dynamic re-prioritization is deferred.

### Q6: Output capability dimensions in data flows

**Problem:** The worked example exposes that `output.map` appears as a data flow sink but is not in required/preferred. Should output channels be explicitly listed in task requirements?

**Options:**
- **(A) Require output capabilities in `preferred` or a new `output` field.** More explicit, enables matching on output capabilities.
- **(B) Allow implicit output sinks.** Data flow sinks prefixed with `output.` are not validated against required/preferred.

**Provisional choice:** (B) for v0.1. Output capabilities are a property of the executing node's infrastructure, not a requirement the task imposes on the executor. Revisit when output routing becomes a design concern.

### Q7: Bid window duration

**Problem:** How long should a bidding round last? Too short — capable nodes in temporary RF shadow miss the window. Too long — delays task execution.

**Options:**
- **(A) Fixed duration.** E.g., 30 seconds. Simple.
- **(B) Adaptive.** Shorter for CRITICAL tasks, longer for OPTIONAL.
- **(C) Quorum-based.** Close bidding when N bids received or timeout, whichever comes first.

**Provisional choice:** (A) for v0.1, with the duration as a configurable parameter (default 30s). Adaptive bidding adds complexity without clear benefit until the system handles real-time pressure.

---

## 15. BASELINE FOR COMPARISON

### Baseline: Task-as-String with Binary Pass/Fail

The simplest possible task model against which HESK's Task Model should be measured:

```
NaiveTask:
  task_id:      string
  description:  string             // human-readable only, not machine-parseable
  requires:     string             // e.g., "needs camera and GPS"
  priority:     HIGH | MEDIUM | LOW
```

**Matching rule:** A human operator reads the task description and manually assigns it to a node, or a simple keyword matcher checks if a node's type-string contains the required keywords.

**Degradation:** None. If the assigned node fails, the task is marked FAILED. No fallback.

**Quality:** Binary. Either the task succeeds or it doesn't. No concept of partial execution.

**Data flow:** Not modeled. Coalition communication requirements are discovered at runtime (or never).

### What HESK's Task Model adds over this baseline

| Dimension | Baseline | HESK Task Model |
|-----------|----------|-----------------|
| Requirements | Free-text string | Structured, machine-readable capability dimensions with thresholds |
| Required vs. preferred | No distinction | Explicit separation enabling degraded-but-feasible matching |
| Degradation | None — binary pass/fail | Ordered tiers with quality estimates and capability subsets |
| Priority | 3-level enum | Continuous (0,1] with derived class (CRITICAL/IMPORTANT/OPTIONAL) |
| Quality floor | None | min_quality prevents wasted effort on useless execution |
| Data flow | Not modeled | Explicit bandwidth/latency requirements for coalition feasibility |
| Lifecycle | Implicit (not started / running / done) | 9-state machine with preconditions, provenance, and full audit trail |
| Provenance | None | Every state carries (node_id, λ) attribution |
| Coalition support | None | Data flows + structured requirements enable multi-node execution |

### Measurable comparison metrics

1. **Degradation recovery rate:** After executor loss, how often does the system find a degraded-but-acceptable re-execution vs. outright failure? (Baseline: always fails.)
2. **Wasted execution ratio:** Fraction of executions producing output below min_quality. (Baseline: unknown — no quality floor.)
3. **Coalition formation success rate:** When no single node suffices, how often does data flow validation correctly predict coalition feasibility? (Baseline: no data flow model.)
4. **State consistency after partition:** On reconnection, how many lifecycle conflicts require human intervention? (Baseline: all — no lifecycle state machine.)
5. **Priority preservation under scarcity:** When resources drop to 40% of initial, what fraction of CRITICAL tasks are still executing? (Baseline: random, since 3-level priority gives poor ordering.)

---

*End of 002_task_model.md — Version 0.1*
