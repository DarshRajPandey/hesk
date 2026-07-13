# 006 — Graceful Degradation

> **Status:** v0.1 draft — HESK's central research contribution  
> **Depends on:** [001 Capability Model](./001_capability_model.md), [002 Task Model](./002_task_model.md), [003 Capability Matching](./003_capability_matching.md), [004 Scarcity Allocation](./004_scarcity_allocation.md), [005 Coalition Formation](./005_coalition_formation.md)  
> **Consumed by:** [008 Partition Reconciliation](./008_partition_reconciliation.md)  
> **Prior art:** Graceful degradation in fault-tolerant systems [Herlihy, 1991], Multi-robot task reallocation [Gerkey & Matarić, 2004]

---

## 1. PROBLEM

### 1.1 Core question

> When resources disappear — nodes crash, sensors fail, links degrade, batteries deplete — how does HESK decide what to preserve, what to degrade, what to reconstruct through coalitions, what to suspend, and what to abandon, such that the surviving system preserves maximum mission utility?

### 1.2 Why this is HESK's central contribution

A conventional multi-robot system operating under failure looks like:

```
100% functionality → 100% → 100% → TOTAL FAILURE
```

HESK should achieve:

```
100% → 82% → 61% → 37% → critical functions preserved
```

The distinction is that HESK does not treat failure as binary.  When a mapping node is lost, the mission does NOT report `MAPPING FAILED`.  Instead, HESK asks:

> What is the highest-value degraded form of this capability that the surviving system can still provide?

This question — the graceful degradation question — is what the existing task allocation literature does not adequately address for heterogeneous swarms under compound resource loss.  Standard Contract Net [Smith, 1980] reallocates failed tasks but does not reason about degradation tiers, priority-ordered service preservation, or coalition-based capability reconstruction.

### 1.3 Scope

This algorithm orchestrates the response to capability loss events.  It calls:
- Algorithm 003 (matching) to check if surviving nodes can satisfy tasks
- Algorithm 004 (allocation) to re-assign tasks to solo nodes
- Algorithm 005 (coalition) to form multi-node teams when solo fails

It decides:
- The order in which tasks are addressed (priority-ordered)
- Which degradation tier each task should operate at
- When to abandon a task entirely
- How to measure the impact of degradation on mission utility

### 1.4 What this algorithm does NOT do

- It does NOT predict failures (anticipatory degradation is a future research direction, §14).
- It does NOT perform partition reconciliation (that is Algorithm 008).
- It does NOT implement responsibility succession as a physical capability transfer (Invariant 4).

---

## 2. DEFINITIONS

### 2.1 Shared notation

| Symbol | Meaning |
|--------|---------|
| n_i | Node i |
| C_i | Capability state of node i (from 001) |
| τ_j | Task j |
| R_j | Requirement state of task j (from 002) |
| π_j | Mission priority of task j ∈ (0, 1] |
| q_min_j | Minimum acceptable quality for task j (from 002) |
| T_j | Set of degradation tiers for task j, ordered [T_0, T_1, ..., T_m] |
| T_j[k] | Tier k of task j.  k=0 is full quality, higher k = more degraded |
| U_swarm | Swarm utility — aggregate measure of mission service quality |
| Γ | Coalition (from 005) |

### 2.2 DegradationTrigger

An event that causes the degradation algorithm to run.

| Trigger type | Description | Source |
|-------------|-------------|--------|
| NODE_LOSS | A node transitions to SUSPECTED_UNREACHABLE or FAILED_CONFIRMED | Heartbeat timeout, failure report |
| CAPABILITY_DEGRADATION | A node's capability drops below its assigned task's requirements | CapabilityReport update, thermal throttle |
| LINK_LOSS | Communication link to a task participant falls below data flow requirement | Link quality monitoring |
| ENERGY_CRITICAL | A node's energy drops below a critical threshold (v0.1: ε < 0.10) | Local energy monitoring |
| COALITION_MEMBER_LOST | A member of an active coalition becomes unreachable or degraded | Coalition health monitoring |

### 2.3 MissionPriorityClass

From Algorithm 002, tasks are classified by priority:

| Class | Priority range | Degradation behavior |
|-------|---------------|---------------------|
| CRITICAL | π_j ∈ [0.8, 1.0] | Degrade last.  Never operate below q_min_j.  If q_min_j is unreachable, abandon with alarm. |
| IMPORTANT | π_j ∈ [0.4, 0.8) | Degrade before CRITICAL.  May operate at lowest tier if necessary. |
| OPTIONAL | π_j ∈ (0, 0.4) | Degrade first.  May be abandoned freely to free resources for higher-priority tasks. |

### 2.4 SwarmUtility

The aggregate measure of how well the mission is being served:

```
U_swarm = Σ (π_j × quality_j)   for all tasks τ_j in state EXECUTING or DEGRADED
```

Where `quality_j` is the quality estimate of the tier at which task j is currently executing (from 002's DegradationTier.quality_estimate).

Tasks in state ABANDONED contribute 0.  Tasks in state COMPLETED contribute their final quality.

**This is a PROVISIONAL v0.1 metric.**  It assumes mission priority and tier quality are independently defined and multiplicatively composable.  A more sophisticated utility function might account for non-linear interactions between tasks (e.g., mapping and surveillance are synergistic).

### 2.5 DegradationPlan

The output of the degradation algorithm:

```
DegradationPlan:
  trigger:              DegradationTrigger
  affected_tasks:       [TaskId]
  tier_changes:         {TaskId: (old_tier, new_tier)}
  new_assignments:      {TaskId: NodeId or Coalition}
  abandoned_tasks:      [TaskId]
  freed_nodes:          [NodeId]                    # nodes released from abandoned/downgraded tasks
  utility_before:       float                       # U_swarm before degradation
  utility_after:        float                       # U_swarm after degradation
  decision_trace:       [TraceEntry]                # explainable log
```

### 2.6 ResponsibilitySuccession

When a node is lost, its **responsibilities** (not physical capabilities — Invariant 4) may be transferred:

```
ResponsibilitySuccession:
  lost_node:            NodeId
  lost_responsibilities: [TaskId]                   # tasks the lost node was executing
  successors:           {TaskId: NodeId or Coalition or ABANDONED}
  succession_type:      {TaskId: SOLO_REASSIGN | COALITION_FORM | TIER_DESCENT | ABANDON}
```

### 2.7 SemanticDegradationLadder

From HESK Scope §12 — multiple representations of the same information at different fidelity levels:

| Level | Representation | Size | Use case |
|-------|---------------|------|----------|
| 0 | Raw LiDAR point cloud | 500 MB | Full 3D reconstruction |
| 1 | Compressed point cloud | 80 MB | Dense mapping |
| 2 | Voxel map | 8 MB | Volumetric occupancy |
| 3 | Object graph | 200 KB | Semantic navigation |
| 4 | Obstacle coordinates + confidence | 120 bytes | Minimum safe navigation |

When communication degrades, the system does not immediately treat a link as unusable.  Instead, it descends the semantic ladder to find the cheapest representation sufficient for the downstream decision.

> This concept is proposed by HESK and should not be presented as established standard terminology.  The underlying idea of multi-resolution information representation is prior art in data compression and sensor fusion.

### 2.8 TraceEntry

For decision explainability (Construction Guide Problem 25):

```
TraceEntry:
  timestamp:            float
  task_id:              TaskId
  action:               REASSIGN | DEGRADE | ABANDON | UPGRADE | SKIP
  reason:               string
  old_tier:             int or None
  new_tier:             int or None
  old_assignee:         NodeId or Coalition or None
  new_assignee:         NodeId or Coalition or None
  quality_change:       (float, float)            # (before, after)
```

---

## 3. ASSUMPTIONS

**A1. Degradation is triggered by events, not by polling.**  A node detects a trigger (heartbeat timeout, capability change, link quality drop) and runs the degradation algorithm.  There is no periodic "check if everything is OK" loop.

**A2. The triggering node runs the algorithm locally.**  Degradation is a LOCAL decision.  The node that detects the trigger computes the plan and broadcasts the decisions.  It does NOT require global consensus before acting — speed is critical when a node has just been lost.

> **This is a PROVISIONAL v0.1 CHOICE.**  This means that if multiple nodes detect the same trigger independently, they may compute conflicting degradation plans.  v0.1 accepts this risk and relies on the local state ledger (007) and partition reconciliation (008) to resolve conflicts.  The alternative — requiring distributed consensus before degradation — is too slow for real-time failure response and requires the very communication that may have just been lost.

**A3. Task degradation tiers are pre-defined.**  Each task's degradation tiers (from 002) are defined at mission planning time.  The degradation algorithm traverses these tiers in order; it does not invent new tiers at runtime.

**A4. Priority classes are pre-defined.**  Mission priority (π_j) and the CRITICAL/IMPORTANT/OPTIONAL classification are set before deployment.  They do not change at runtime (in v0.1).

**A5. Degradation is reversible.**  If resources return (node reconnects, battery recovers, link quality improves), the system may attempt to upgrade tasks back to higher tiers.

**A6. The degradation algorithm has access to the locally-known swarm state.**  It can check which nodes are currently known (via received CapabilityReports), which tasks are assigned where, and what resources are available.  All of this is from the local state ledger (007) — never from global simulation truth.

---

## 4. INPUTS

### Per degradation trigger event

| Input | Source | Description |
|-------|--------|-------------|
| trigger | Local detection | DegradationTrigger specifying what failed |
| affected_tasks | Local ledger | Tasks assigned to or dependent on the lost resource |
| current_assignments | Local ledger | Map of {task → assignee (node or coalition)} |
| current_tiers | Local ledger | Map of {task → current operating tier} |
| known_nodes | Local ledger + received reports | Set of currently-known available nodes with capability states |
| link_metrics | Local measurement | Communication quality to known nodes |

### Configuration (mission-level)

| Parameter | Description | v0.1 default |
|-----------|-------------|-------------|
| ε_critical | Energy threshold below which a node is considered energy-critical | 0.10 |
| heartbeat_timeout_s | Seconds without heartbeat before SUSPECTED_UNREACHABLE | 5.0 |
| degradation_cascade_limit | Max number of cascading degradation rounds per trigger | 3 |

---

## 5. LOCALLY AVAILABLE INFORMATION

### KNOWN LOCALLY
- Own capability state C_i (fresh)
- Own currently assigned tasks and their tiers
- Own energy level ε_i
- Time since last heartbeat from each known neighbor

### RECEIVED VIA MESSAGES
- CapabilityReports from neighbor nodes (with staleness)
- Task assignment records from the local state ledger
- Heartbeats from active nodes (or absence thereof)
- Link quality metrics

### INFERRED
- Which tasks are affected by a specific loss event (computed from assignment records)
- Whether surviving nodes can satisfy tasks at various tiers (computed via 003)
- Potential coalition compositions (computed via 005)
- Swarm utility before and after degradation (computed from priority × quality)

### UNKNOWN
- True state of the lost node (it may only be temporarily unreachable, not dead — Invariant 7)
- Capabilities of unreachable nodes beyond communication horizon
- Whether other nodes are also running degradation logic for the same trigger event
- Future trigger events (cannot predict next failure)
- Whether the lost node will return (and when)

---

## 6. OUTPUT

### Primary output: DegradationPlan (§2.5)

Contains:
- Tier changes for each affected task
- New assignments (solo or coalition)
- Abandoned tasks
- Utility change
- Decision trace

### Secondary outputs

- **Responsibility succession records** — which responsibilities transferred to whom
- **Freed node list** — nodes released from abandoned/downgraded tasks (now available for other work)
- **Broadcast messages** — degradation decisions propagated to reachable neighbors for ledger update

---

## 7. DECISION RULE

### 7.1 Priority-ordered degradation (Greedy Heuristic)

The fundamental rule: **degrade lower-priority tasks first to preserve resources for higher-priority tasks.**

Because HESK is decentralized and operates on local knowledge, this degradation algorithm acts as a **greedy heuristic**, not a globally optimal solver. When a node detects a failure, it immediately attempts to resolve CRITICAL tasks using the resources it knows about *right now*. It does not perform a global combinatorial search, nor does it wait for consensus.

Ordering:
1. Process CRITICAL tasks first (attempt to maintain highest possible tier)
2. Process IMPORTANT tasks second (may degrade to free resources for CRITICAL)
3. Process OPTIONAL tasks last (may be abandoned to free resources)

Within the same priority class, process tasks by descending π_j (highest priority first).

### 7.2 Tier traversal

For each affected task, starting from its current tier:

```
function find_best_satisfaction(task, current_tier, available_nodes):
    for tier in task.tiers[current_tier ... max_tier]:
        requirement = tier.required
        
        # Try solo re-assignment
        eligible_nodes = [n for n in available_nodes if check_eligibility(C_n, requirement)]
        if eligible_nodes:
            best_node = select_by_system_cost(eligible_nodes, task)  # Algorithm 004 logic
            return (SOLO_REASSIGN, best_node, tier)
        
        # Try coalition formation
        coalition = form_coalition(task_at_tier, available_nodes, link_metrics)  # Algorithm 005
        if coalition.success:
            return (COALITION_FORM, coalition, tier)
    
    # No tier satisfiable
    return (ABANDON, None, None)
```

### 7.3 Swarm utility maximization

The degradation algorithm should maximize post-degradation U_swarm:

```
U_swarm = Σ (π_j × quality_j)   for all active tasks
```

Where quality_j = DegradationTier[current_tier_j].quality_estimate.

When multiple degradation options exist (e.g., degrade task A vs. task B), prefer the option that yields higher U_swarm.

### 7.4 Resource freeing

Degrading a task from Tier 0 to Tier 2 may reduce its resource requirements.  The freed resources (compute capacity, bandwidth, etc.) become available for other tasks.  Similarly, abandoning a task frees its assignee entirely.

The algorithm tracks freed resources and re-evaluates whether previously-degraded higher-priority tasks can now be upgraded.

### 7.5 Cascade limit

Degradation can cascade: degrading task A frees Node X, which can now handle task B at a higher tier.  But this reallocation might make Node Y redundant, triggering further changes.

v0.1 limits cascading to `degradation_cascade_limit` (default: 3) rounds.  After the limit, the algorithm stabilizes at the current state even if further improvements are theoretically possible.

### 7.6 Abandonment criteria

A task is abandoned when:
1. No tier is satisfiable by any available node or coalition, OR
2. The task is OPTIONAL and its resources are needed for a CRITICAL task, OR
3. The task's best achievable quality is below q_min_j (minimum acceptable quality)

Abandonment of a CRITICAL task generates an alarm in the decision trace.

### 7.7 Recovery (upgrade)

When a resource-recovery event occurs (node reconnects, energy replenished, link quality improves):

```
function attempt_upgrade(recovered_resource, current_assignments):
    for task in current_assignments sorted by π_j descending:
        if task.current_tier > 0:  # currently degraded
            higher_tier = task.current_tier - 1
            if find_best_satisfaction(task, higher_tier, available_nodes):
                upgrade task to higher_tier
                update assignments
    return updated_assignments
```

Recovery is opportunistic — it runs when a positive event is detected, not on a timer.

### 7.8 Enforcing the Priority Invariant (Cooperative Release)

A known limitation of greedy, decentralized allocation is **priority inversion**: a lower-priority task (Task B, IMPORTANT) might hold a scarce resource that a newly degraded higher-priority task (Task A, CRITICAL) desperately needs.

Because HESK does not support unilateral preemption (nodes cannot forcibly commandeer other nodes), the priority invariant is enforced through **cooperative release and lease expiration**:

1. **Cooperative Release:** When a node running Task B receives a degradation plan broadcast indicating that Task A (where π_A > π_B) is failing or operating at a severely degraded tier due to lack of the resource Task B is holding, the node running Task B *voluntarily* degrades or abandons its task to free the resource.
2. **Lease Expiration:** Task assignments operate on time-bound leases (e.g., 30-second renewals). If Task A cannot acquire the resource cooperatively, Task B's lease will eventually expire. During the subsequent bidding round (if Task B attempts renewal), Task A's higher priority will win the resource allocation over Task B.

---

## 8. PLAIN-ENGLISH ALGORITHM

### Degradation Response Protocol

1. **TRIGGER DETECTION.**  A node detects a capability-loss event (heartbeat timeout, capability drop, link failure, energy critical, coalition member lost).

2. **IDENTIFY AFFECTED TASKS.**  Query the local state ledger for all tasks assigned to or dependent on the lost resource.  This includes tasks assigned to the lost node AND tasks whose coalitions include the lost node.

3. **SNAPSHOT.**  Record U_swarm_before = Σ(π_j × quality_j) over all currently-active tasks.

4. **SORT.**  Sort affected tasks by priority:
   - First: CRITICAL tasks (descending π_j)
   - Then: IMPORTANT tasks (descending π_j)
   - Finally: OPTIONAL tasks (descending π_j)

5. **FOR EACH AFFECTED TASK** (highest priority first):
   a. Determine the current tier.
   b. Try to re-satisfy at the CURRENT tier first:
      - Check solo eligibility among available nodes (Algorithm 003).
      - If eligible nodes exist, select the best by system cost (Algorithm 004 logic).
      - If no solo node eligible, attempt coalition formation (Algorithm 005).
   c. If current tier fails, descend to the next lower tier.  Repeat 5b.
   d. Continue tier descent until:
      - A tier is satisfied → assign at that tier, record quality.
      - All tiers exhausted → ABANDON the task.

6. **RESOURCE FREEING.**  After processing all affected tasks, compute freed resources (nodes no longer assigned to abandoned/downgraded tasks).  Check if any previously-degraded higher-priority task can now be upgraded with freed resources (limited by cascade_limit).

7. **COMPUTE UTILITY.**  U_swarm_after = Σ(π_j × quality_j) over all tasks in their new states.

8. **LOG DECISION TRACE.**  For each task affected, record: action, old tier, new tier, old assignee, new assignee, quality change, reason.

9. **BROADCAST.**  Send degradation decisions to reachable neighbors.  Each neighbor updates its local state ledger with the new assignments and tiers.

---

## 9. PSEUDOCODE

```python
def handle_degradation_trigger(trigger, local_ledger, known_nodes, link_metrics):
    """
    Main entry point for degradation response.
    Runs locally on the node that detected the trigger.
    No global state is accessed.
    """
    # Step 1: Identify affected tasks
    affected_tasks = identify_affected_tasks(trigger, local_ledger)
    
    if not affected_tasks:
        return None  # trigger does not affect any known task
    
    # Step 2: Snapshot utility
    all_tasks = local_ledger.get_all_active_tasks()
    utility_before = compute_swarm_utility(all_tasks)
    
    # Step 3: Sort by priority (CRITICAL first, then IMPORTANT, then OPTIONAL)
    affected_tasks.sort(key=lambda t: t.priority, reverse=True)
    
    # Step 4: Track available nodes (excluding lost/degraded ones)
    available_nodes = get_available_nodes(known_nodes, trigger)
    
    # Step 5: Process each affected task
    tier_changes = {}
    new_assignments = {}
    abandoned = []
    trace = []
    
    for task in affected_tasks:
        result = find_best_satisfaction_with_descent(task, available_nodes, link_metrics)
        
        if result.action == SOLO_REASSIGN:
            new_assignments[task.id] = result.assignee
            tier_changes[task.id] = (task.current_tier, result.tier)
            # Commit the assigned node (remove from available for subsequent tasks)
            available_nodes.remove_commitment(result.assignee, task)
            trace.append(TraceEntry(
                task_id=task.id, action=REASSIGN,
                reason=f"Solo reassignment to {result.assignee} at tier {result.tier}",
                old_tier=task.current_tier, new_tier=result.tier,
                quality_change=(task.current_quality, result.tier.quality_estimate)
            ))
        
        elif result.action == COALITION_FORM:
            new_assignments[task.id] = result.coalition
            tier_changes[task.id] = (task.current_tier, result.tier)
            for member in result.coalition.members:
                available_nodes.remove_commitment(member, task)
            trace.append(TraceEntry(
                task_id=task.id, action=DEGRADE,
                reason=f"Coalition {result.coalition.members} at tier {result.tier}",
                old_tier=task.current_tier, new_tier=result.tier,
                quality_change=(task.current_quality, result.tier.quality_estimate)
            ))
        
        elif result.action == ABANDON:
            abandoned.append(task.id)
            # Free the nodes that WERE assigned to this task (if any survived)
            freed = release_task_resources(task, local_ledger)
            available_nodes.add_freed(freed)
            trace.append(TraceEntry(
                task_id=task.id, action=ABANDON,
                reason=f"No tier satisfiable. Best partial: {result.best_partial}",
                old_tier=task.current_tier, new_tier=None,
                quality_change=(task.current_quality, 0.0)
            ))
            if task.priority_class == CRITICAL:
                trace.append(TraceEntry(
                    task_id=task.id, action=ALARM,
                    reason="CRITICAL task abandoned — mission integrity compromised"
                ))
    
    # Step 6: Cascade — check if freed resources enable upgrades
    cascade_round = 0
    while cascade_round < DEGRADATION_CASCADE_LIMIT:
        upgrades = attempt_upgrades(all_tasks, available_nodes, link_metrics)
        if not upgrades:
            break
        for task_id, new_tier, assignee in upgrades:
            tier_changes[task_id] = (tier_changes.get(task_id, (None,))[1] or task.current_tier, new_tier)
            new_assignments[task_id] = assignee
            trace.append(TraceEntry(
                task_id=task_id, action=UPGRADE,
                reason=f"Freed resources enabled upgrade to tier {new_tier}",
            ))
        cascade_round += 1
    
    # Step 7: Compute post-degradation utility
    utility_after = compute_swarm_utility_with_changes(all_tasks, tier_changes, abandoned)
    
    # Step 8: Build degradation plan
    plan = DegradationPlan(
        trigger=trigger,
        affected_tasks=[t.id for t in affected_tasks],
        tier_changes=tier_changes,
        new_assignments=new_assignments,
        abandoned_tasks=abandoned,
        utility_before=utility_before,
        utility_after=utility_after,
        decision_trace=trace
    )
    
    # Step 9: Broadcast
    broadcast_degradation_plan(plan, reachable_neighbors)
    
    # Step 10: Update local ledger
    local_ledger.apply_degradation_plan(plan)
    
    return plan


def find_best_satisfaction_with_descent(task, available_nodes, link_metrics):
    """Try to satisfy task at current tier, then descend through degradation tiers."""
    
    for tier_idx in range(task.current_tier, len(task.degradation_tiers)):
        tier = task.degradation_tiers[tier_idx]
        
        if tier.quality_estimate < task.minimum_acceptable_quality:
            continue  # this tier is below the quality floor
        
        requirement = tier.required
        
        # Try solo
        eligible = [n for n in available_nodes if check_eligibility(n.C, requirement)]
        if eligible:
            best = min(eligible, key=lambda n: compute_system_cost(n, task, available_nodes))
            return SatisfactionResult(
                action=SOLO_REASSIGN, assignee=best.id, tier=tier
            )
        
        # Try coalition
        coalition_result = form_coalition(task.with_tier(tier), available_nodes, link_metrics)
        if coalition_result.success:
            return SatisfactionResult(
                action=COALITION_FORM, coalition=coalition_result.coalition, tier=tier
            )
    
    # All tiers exhausted
    return SatisfactionResult(action=ABANDON, best_partial=last_partial_info)


def compute_swarm_utility(tasks):
    """U_swarm = Σ(π_j × quality_j) for all active tasks."""
    return sum(t.priority * t.current_quality for t in tasks if t.status in [EXECUTING, DEGRADED])


def attempt_upgrades(all_tasks, available_nodes, link_metrics):
    """Check if any degraded task can be upgraded with currently available resources."""
    upgrades = []
    for task in sorted(all_tasks, key=lambda t: t.priority, reverse=True):
        if task.current_tier > 0 and task.status in [EXECUTING, DEGRADED]:
            higher_tier = task.degradation_tiers[task.current_tier - 1]
            result = find_best_satisfaction_at_tier(task, higher_tier, available_nodes, link_metrics)
            if result.success:
                upgrades.append((task.id, higher_tier, result.assignee))
    return upgrades
```

---

## 10. WORKED EXAMPLE

### Scenario: progressive mapping degradation (from HESK Scope §5)

**Initial state: full swarm (5 nodes)**

| Node | Key capabilities | Assigned task | Tier | Quality |
|------|-----------------|---------------|------|---------|
| Node A | camera=0.9, lidar=0.8, gpu=0.7, cuda | mapping_zone_b | 0 (full 3D) | 1.0 |
| Node B | camera=0.85, localization=0.9, compute=0.3 | surveillance_zone_c | 0 | 0.9 |
| Node C | compute=1.0, cuda, vram=4096 | relay_support | 0 | 0.8 |
| Node D | thermal=1, camera=0.4, mobility=0.9 | patrol_perimeter | 0 | 0.85 |
| Node E | radio=strong, relay | comm_relay | 0 | 1.0 |

**Tasks and priorities:**

| Task | Priority (π) | Class | Min quality |
|------|-------------|-------|------------|
| mapping_zone_b | 0.91 | CRITICAL | 0.40 |
| surveillance_zone_c | 0.72 | IMPORTANT | 0.30 |
| patrol_perimeter | 0.55 | IMPORTANT | 0.25 |
| comm_relay | 0.85 | CRITICAL | 0.50 |
| relay_support | 0.35 | OPTIONAL | 0.20 |

**U_swarm_initial** = 0.91×1.0 + 0.72×0.9 + 0.55×0.85 + 0.85×1.0 + 0.35×0.8 = 0.91 + 0.648 + 0.4675 + 0.85 + 0.28 = **3.1555**

---

### Event 1: Node A crashes

**Trigger:** heartbeat_timeout for Node A after 5.0 seconds.  Node B detects the trigger.

**Step 1: Identify affected tasks.**  
mapping_zone_b was assigned to Node A → affected.

**Step 2: Snapshot.** U_swarm_before = 3.1555

**Step 3: Sort affected tasks.** Only one: mapping_zone_b (CRITICAL, π=0.91).

**Step 4: Available nodes:** {B, C, D, E} (A lost).

**Step 5: Find satisfaction for mapping_zone_b.**

**mapping_zone_b degradation tiers:**
- Tier 0: Full 3D mapping (camera≥0.7, lidar≥0.8, gpu≥0.5, runtime=cuda) → quality 1.0
- Tier 1: Dense visual mapping (camera≥0.7, gpu≥0.4, runtime∈{cuda,opencl}) → quality 0.70
- Tier 2: Sparse landmark mapping (camera≥0.6) → quality 0.40

**Try Tier 0:**
- Solo check: B(no lidar, no cuda), C(no camera, no lidar), D(camera=0.4 < 0.7), E(no camera) → no eligible solo.
- Coalition: Need camera≥0.7, lidar≥0.8, gpu≥0.5, cuda.  No surviving node has lidar≥0.8 → coalition FAILS.
- Tier 0 unsatisfiable.

**Try Tier 1:**  
Required: camera≥0.7, gpu≥0.4, runtime∈{cuda, opencl}
- Solo check: B(camera=0.85✓, compute=0.3 as gpu? → 0.3<0.4✗), C(no camera✗), D(camera=0.4✗), E(no camera✗) → no eligible solo.
- Coalition: B provides camera (0.85), C provides gpu (1.0, cuda).
  - B↔C link: bandwidth=3000 kbps, latency=80ms.
  - Data flow: camera→gpu needs 5000 kbps.  3000 < 5000 → **comm INFEASIBLE at Tier 1** with raw video.
  - *However*: at Tier 1 (dense visual, not full 3D), compressed video at 3000 kbps may suffice.  This is a **Semantic Degradation Ladder** application — descend data fidelity to match bandwidth.
  
> **Design decision:** v0.1 uses the data flow requirements as stated in the tier definition.  If Tier 1's data flow specifies 3000 kbps (for compressed video), the coalition is feasible.  If it specifies 5000 kbps (same as Tier 0), it fails, and we descend to Tier 2.
>
> For this example, assume Tier 1 data flow requires 3000 kbps (compressed): **FEASIBLE.**

- Coalition {B, C} satisfies Tier 1.  Cost = exec_B + exec_C + coord + frag = 1.65 (estimated).
- **ASSIGN coalition {B, C} at Tier 1, quality = 0.70.**

**But wait:** Node B is currently executing surveillance_zone_c.  Assigning B to the mapping coalition means surveillance loses its executor.

**Cascade check:** surveillance_zone_c (IMPORTANT, π=0.72) is now unassigned.
- Try solo: D(camera=0.4 — may not meet surveillance camera≥0.5), E(no camera).
- If D can execute surveillance at Tier 1 (reduced quality), assign D.
- If not, surveillance may need to degrade or be abandoned.

For this example: surveillance Tier 1 requires camera≥0.3.  D has camera=0.4 ✓.  Assign D at Tier 1, quality=0.55.

But D was executing patrol_perimeter.  Another cascade.  patrol_perimeter (IMPORTANT, π=0.55) is now unassigned.  No suitable node → ABANDON (all remaining nodes are committed).

**Cascade limit:** 2 rounds of cascade used.

**Step 6: Freed nodes.** Node D freed from patrol_perimeter (but immediately reassigned to surveillance).

**Step 7: Compute utility.**

| Task | New state | Quality |
|------|-----------|---------|
| mapping_zone_b | Tier 1 (coalition {B,C}) | 0.70 |
| surveillance_zone_c | Tier 1 (Node D) | 0.55 |
| patrol_perimeter | ABANDONED | 0.0 |
| comm_relay | Unchanged (Node E) | 1.0 |
| relay_support | Unchanged (Node C was doing this, now in coalition) | ABANDONED* |

*relay_support was on Node C, which is now in the mapping coalition.  It too cascades to abandonment.

U_swarm_after = 0.91×0.70 + 0.72×0.55 + 0 + 0.85×1.0 + 0 = 0.637 + 0.396 + 0.85 = **1.883**

**Decision trace:**
```
TASK mapping_zone_b: DEGRADE Tier 0→1, coalition {B,C}, quality 1.0→0.70
  Reason: Node A lost, lidar unavailable, Tier 0 unsatisfiable
TASK surveillance_zone_c: DEGRADE Tier 0→1, reassign to Node D, quality 0.9→0.55
  Reason: Node B reassigned to mapping coalition
TASK patrol_perimeter: ABANDON
  Reason: Node D reassigned to surveillance, no capable substitute
TASK relay_support: ABANDON
  Reason: Node C reassigned to mapping coalition
U_swarm: 3.1555 → 1.883 (Δ = -1.2725, -40.3%)
CRITICAL tasks preserved: mapping_zone_b (degraded), comm_relay (unchanged)
```

---

### Event 2: Node C also crashes (further degradation)

**Trigger:** Node C unreachable.

**Affected tasks:** mapping_zone_b (coalition {B,C} — member C lost).

**Try re-satisfy mapping at Tier 1:** Need gpu≥0.4 with cuda.  Only remaining compute nodes: D(no gpu), E(no compute).  No solo or coalition satisfies Tier 1.

**Try Tier 2 (sparse landmark mapping):** camera≥0.6.  Node B has camera=0.85 ✓.  **Solo execution at Tier 2.**

Assign Node B to mapping_zone_b at Tier 2, quality=0.40.

U_swarm_after = 0.91×0.40 + 0.72×0.55 + 0.85×1.0 = 0.364 + 0.396 + 0.85 = **1.610**

**Decision trace:**
```
TASK mapping_zone_b: DEGRADE Tier 1→2, solo Node B, quality 0.70→0.40
  Reason: Node C lost, coalition {B,C} dissolved, Tier 1 unsatisfiable
  NOTE: mapping quality now at minimum acceptable (0.40 = q_min)
U_swarm: 1.883 → 1.610 (Δ = -0.273, -14.5%)
CRITICAL mapping preserved at minimum quality
```

---

## 11. EDGE CASES

### E1: All coalition members fail simultaneously

A coalition {B, C, D} loses all three members at once (e.g., common-cause failure like RF interference in an area).

**Handling:** The degradation algorithm processes the task as if it has zero resources.  It walks all tiers.  If no solo node from the surviving swarm can satisfy any tier → ABANDON.  This is a legitimate outcome — HESK does not promise infinite resilience.

### E2: Cascading degradation spiral

Degrading task A frees Node X, which enables task B to upgrade.  But the upgrade requires Node Y, which was serving task C.  Task C now needs to degrade, freeing resources... leading to an infinite loop.

**Handling:** The `degradation_cascade_limit` (default: 3) breaks the loop.  After 3 cascade rounds, the algorithm stops even if further improvements are possible.

### E3: CRITICAL task unsatisfiable at any tier

A CRITICAL task (e.g., mapping at π=0.91) cannot be satisfied at any tier — no surviving node has any relevant capability.

**Handling:** The task is ABANDONED with an ALARM trace entry.  This is an exceptional condition indicating mission integrity is compromised.  v0.1 logs the alarm but takes no further automatic action.

### E4: Concurrent degradation decisions

Nodes B and D both detect Node A's heartbeat timeout simultaneously.  Both independently run degradation for mapping_zone_b.  B assigns mapping to coalition {B, C}.  D assigns mapping to coalition {D, E}.

**Handling:** This creates a conflicting assignment (EXCLUSIVE_OWNERSHIP conflict on task_owner.mapping).  The conflict is resolved by the local state ledger (007) and partition reconciliation (008).  v0.1 uses a deterministic tiebreak: the assignment with the higher quality tier wins.  If tied, the assignment from the lower-ID node wins.

### E5: Recovery — lost node returns

Node A reconnects after being SUSPECTED_UNREACHABLE.  It was executing mapping at Tier 0.

**Handling:** Node A's return is a resource-recovery event.  The degradation algorithm runs `attempt_upgrade()`.  If Node A still has its capabilities (lidar, gpu, cuda), mapping could potentially be upgraded back from Tier 2 to Tier 0.  But Node A may have conflicting state (it thinks it still owns mapping).  This is a reconciliation problem (008).

### E6: Degradation frees resources enabling different task upgrades

Abandoning an OPTIONAL task frees a high-compute node.  A CRITICAL task currently at Tier 2 could be upgraded to Tier 0 with that node.

**Handling:** The cascade logic in Step 6 handles this.  After abandoning the OPTIONAL task, the freed node is re-evaluated for all degraded higher-priority tasks.

---

## 12. FAILURE MODES

### F1: Thrashing between tiers

A node's capability oscillates near a threshold (e.g., CPU oscillates between 0.49 and 0.51, with threshold at 0.50).  The task repeatedly degrades and upgrades.

**Mitigation:** Hysteresis in capability assessment (defined in 001).  A capability must drop below `threshold - hysteresis_margin` to trigger degradation, and rise above `threshold + hysteresis_margin` to enable upgrade.

### F2: Stale information causes unnecessary degradation

The degradation algorithm believes Node C has gpu=0.3 (stale report), so it abandons Tier 1.  Actually C has gpu=0.8 (the report was old).

**Mitigation:** Before making an irrevocable decision (ABANDON), the algorithm should prefer reversible decisions (DEGRADE) and attempt to refresh stale capability reports by requesting updates from relevant nodes.

### F3: Two nodes make conflicting degradation decisions

Covered in E4.  The fundamental risk of distributed degradation is inconsistent decisions.  v0.1 accepts this and relies on eventual reconciliation.

### F4: Degradation blocks recovery

After degradation, all nodes are committed to degraded tasks.  When the lost node returns with full capability, no node can be freed to form a higher-quality coalition because all are assigned.

**Mitigation:** The upgrade logic should consider task preemption — a returned high-capability node may justify preempting a lower-priority task's assignee.  v0.1 does NOT implement preemption (open question Q3).

---

## 13. INVARIANTS

**I1. Priority ordering is respected.**  OPTIONAL tasks degrade before IMPORTANT, which degrade before CRITICAL.  No CRITICAL task degrades while an OPTIONAL task holds resources it could use.

**I2. No node accesses global truth.**  All degradation decisions are based on locally-known state and received messages.

**I3. Capabilities are not transferred.**  When Node A is lost, its LiDAR capability is lost.  Node B cannot "inherit" the LiDAR.  It can only inherit the RESPONSIBILITY (task).

**I4. Every degradation decision has a trace.**  No task changes tier, assignee, or status without a logged TraceEntry.

**I5. Abandoned tasks contribute zero utility.**  U_swarm never counts quality from abandoned tasks.

**I6. CRITICAL tasks are never voluntarily degraded below q_min.**  If no tier satisfies q_min, the task is ABANDONED (with alarm), not executed at unacceptable quality.

**I7. Degradation is a local decision broadcast to neighbors.**  The triggering node acts and then broadcasts.  It does not wait for consensus.

**I8. Cascade depth is bounded.**  No degradation trigger causes more than `degradation_cascade_limit` rounds of cascading.

---

## 14. OPEN QUESTIONS

### Q1: Who initiates degradation?

**Question:** When a node is lost, which surviving node should run the degradation algorithm?

**Options:**
- **First detector:** The first node to detect the heartbeat timeout runs it.
- **Task stakeholders:** Each node that had a task affected by the loss runs it independently for its own tasks.
- **Designated responders:** Pre-assigned nodes for degradation response.

**Provisional v0.1 choice:** First detector for the affected tasks.  The node that detects the trigger and knows about the affected task runs degradation.  If multiple nodes detect the same trigger, they may run concurrently (accepted inconsistency, resolved by 008).

### Q2: Concurrent degradation handling

**Question:** How to handle the case where Nodes B and D both detect the same trigger and compute conflicting degradation plans?

**Options:**
- **Accept and reconcile:** Let both run, resolve conflicts via 007/008.
- **Leader election:** Elect a degradation coordinator (adds latency, requires communication).
- **Deterministic tiebreak:** Ensure both nodes compute the SAME plan by using a deterministic algorithm with the same inputs.

**Provisional v0.1 choice:** Accept and reconcile.  The algorithm is deterministic given the same inputs, but different nodes may have different inputs (different sets of CapabilityReports).  Reconciliation (008) handles the inconsistency.

### Q3: Task preemption during recovery

**Question:** When a high-capability node returns, should HESK preempt lower-priority tasks to free resources for upgrading higher-priority tasks?

**Options:**
- **No preemption (v0.1):** Only upgrade tasks if free resources exist.
- **Priority-based preemption:** Preempt OPTIONAL tasks to upgrade CRITICAL tasks.

**Provisional v0.1 choice:** No preemption.  Preemption adds significant complexity (interrupted tasks may lose progress).  Deferred to v0.2.

### Q4: Anticipatory degradation

**Question:** Should HESK predict imminent failures (declining battery, worsening link quality) and pre-position successors BEFORE the failure occurs?

This is discussed in HESK Scope §18:
> Can lightweight local signals allow useful pre-failure preparation without wasting excessive bandwidth and compute on false predictions?

**v0.1 approach:** NOT implemented.  The degradation algorithm is reactive.  Anticipatory degradation is a significant research direction that requires:
- Trend detection on capability time series
- Failure probability estimation
- Cost-benefit analysis of preemptive action vs. false alarm waste

Deferred as a research topic, not a v0.1 feature.

### Q5: How to evaluate degradation quality?

**Question:** How to prove that HESK's degradation approach preserves more mission utility than alternatives?

**Answer:** Compare U_swarm preservation curves under progressive resource loss scenarios:
- X-axis: fraction of swarm resources lost (0% to 80%)
- Y-axis: U_swarm preserved (fraction of initial)
- Compare HESK vs. baselines A, B, C (see §15)

If HESK's U_swarm curve is consistently above the baselines, the degradation algorithm is demonstrably better.

---

## 15. BASELINE FOR COMPARISON

### Baseline A: Binary fail-stop

When a resource is lost, any task that depended on it → FAILED.  No tier descent, no re-assignment, no coalition formation.

```
Node A lost → mapping FAILED
→ U_swarm drops by π_mapping × quality_mapping = 0.91 × 1.0 = 0.91
No recovery attempt.
```

### Baseline B: Random reassignment

When a resource is lost, affected tasks are randomly assigned to surviving nodes regardless of capability match.

```
Node A lost → mapping randomly assigned to Node E (relay node, no camera)
→ Node E cannot execute mapping
→ Task fails anyway (or produces garbage output at quality ≈ 0)
```

### Baseline C: Greedy reassignment without degradation tiers

When a resource is lost, try to find a surviving node that matches the ORIGINAL (Tier 0) requirements.  If none exists → FAIL.  No tier descent.

```
Node A lost → need camera≥0.7, lidar≥0.8, gpu≥0.5, cuda
→ No surviving solo node has lidar → FAIL
→ U_swarm drops by 0.91 (same as Baseline A for this scenario)
```

### HESK comparison

```
Node A lost → Tier 0 fails (no lidar)
→ Tier 1 attempted: coalition {B, C} at quality 0.70 → SUCCESS
→ U_swarm drops by 0.91 × (1.0 - 0.70) = 0.273
→ Mission continues at reduced but useful quality
```

### Comparison metrics

| Metric | Baseline A | Baseline B | Baseline C | HESK 006 |
|--------|-----------|-----------|-----------|----------|
| Mapping preserved after Node A loss | No | Random (likely no) | No | Yes (Tier 1) |
| U_swarm after Node A loss | 2.2455 | ≈2.2455 | 2.2455 | 2.6055+ |
| Tasks continuing after 2 node losses | Lower | Random | Lower | Higher |
| Critical task preservation | Not guaranteed | Not guaranteed | Not guaranteed | Priority-ordered |
| Decision explainability | "Failed" | "Randomly assigned to X" | "No match found" | Full trace |
