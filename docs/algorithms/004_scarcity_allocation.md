# 004 — Scarcity-Aware Task Allocation

## 1. PROBLEM

Given a set of eligible nodes (determined by Algorithm 003) and a task to execute, decide **which eligible node should execute the task** while minimizing total system cost including the opportunity cost of consuming scarce capabilities.

A naive allocator selects the cheapest immediate executor. This is wrong when the cheapest node possesses a unique or rare capability that may be needed by future tasks. Assigning that node to a non-requiring task wastes a strategically scarce system resource.

### Core question

> What is the true system-level cost of assigning node n_i to task τ_j, accounting for execution cost, energy cost, communication cost, and the future option loss from consuming scarce capabilities?

This algorithm extends the Contract Net Protocol [Smith 1980] with scarcity-aware bid evaluation. The Contract Net Protocol itself is prior art and NOT a HESK invention. HESK's contribution is the scarcity penalty term and the degradation-aware cost model integrated into the bidding framework.

### Dependencies

| Algorithm | Provides to 004 |
|-----------|-----------------|
| 001 — Capability Model | Capability state vectors `C_i`, dimension set `D`, capability values `c_{i,d}` |
| 002 — Task Model | Task requirement vectors `R_j`, priority `p_j`, required dimensions `D_j^req` |
| 003 — Capability Matching | Eligible set `E_j ⊆ S`, match quality `q(n_i, τ_j)` per eligible node |

---

## 2. DEFINITIONS

### Notation

| Symbol | Type | Meaning |
|--------|------|---------|
| `S` | set | Current locally-known swarm (set of node identifiers) |
| `n_i` | element | Node with index `i`, member of `S` |
| `τ_j` | element | Task with index `j` |
| `D` | set | Set of all capability dimensions (e.g., thermal, lidar, rgb, compute, …) |
| `c_{i,d}` | float ∈ [0,1] | Node `n_i`'s current capability value on dimension `d` |
| `C_i` | vector | Node `n_i`'s full capability state: `C_i = {c_{i,d} : d ∈ D}` |
| `D_j^req` | set | Dimensions **required** by task `τ_j` (from 002) |
| `D_j^pref` | set | Dimensions **preferred** by task `τ_j` (from 002) |
| `R_j` | vector | Task requirement state for `τ_j` (from 002) |
| `E_j` | set | Eligible nodes for `τ_j`: `E_j ⊆ S` (from 003) |
| `q(n_i, τ_j)` | float ∈ [0,1] | Match quality of node `n_i` for task `τ_j` (from 003) |
| `p_j` | float ∈ [0,1] | Mission priority of task `τ_j` (from 002) |
| `e_i` | float ∈ [0,1] | Energy state of node `n_i` (1.0 = full, 0.0 = depleted) |
| `σ_d(S)` | float ∈ [0,1] | Scarcity of capability dimension `d` across locally-known swarm `S` |
| `θ_d` | float ∈ [0,1] | Meaningful capability threshold for dimension `d` |
| `w_exec` | float ≥ 0 | Weight for execution cost component |
| `w_energy` | float ≥ 0 | Weight for energy cost component |
| `w_scarcity` | float ≥ 0 | Weight for scarcity penalty component |
| `w_comm` | float ≥ 0 | Weight for communication cost component |
| `Δt_bid` | duration | Bid collection window duration |

### Key terms

**Scarcity (σ_d):** A measure of how rare a capability dimension `d` is across the locally-known swarm. High scarcity means few nodes possess meaningful levels of dimension `d`.

**Scarcity penalty:** The additional system cost incurred when a node with scarce capabilities is assigned to a task that does not require those capabilities. It penalizes **wasting** scarce resources, not using them.

**System cost:** The weighted sum of execution cost, energy cost, scarcity penalty, and communication cost. This is the objective function minimized during bid evaluation.

**Announcer:** The node that discovers or owns the task and initiates the bidding protocol.

**Bidder:** An eligible node that evaluates local suitability and submits a bid.

**Bid:** A message containing the bidder's computed system cost, match quality, and a capability snapshot. Bids are self-assessed — each node computes its own cost.

**Contract Net Protocol (CNP):** A task allocation protocol where a manager announces a task, agents submit bids, and the manager selects a winner [Smith, R.G. "The Contract Net Protocol: High-Level Communication and Control in a Distributed Problem Solver." IEEE Transactions on Computers, 1980]. This is established prior art.

**Meaningful capability:** A capability value `c_{i,d} ≥ θ_d` where `θ_d` is the minimum threshold for dimension `d` to be considered operationally useful (not noise, not residual).

---

## 3. ASSUMPTIONS

**A1.** Algorithm 003 has already produced the eligible set `E_j` and match quality `q(n_i, τ_j)` for each eligible node. Only eligible nodes participate in bidding.

**A2.** Each node knows its own capability state `C_i` and energy state `e_i` with reasonable accuracy. These are local measurements, not remote estimates.

**A3.** Each node has received recent capability reports from some subset of the swarm. The locally-known swarm `S` may be smaller than the true swarm due to partitions or message loss.

**A4.** Scarcity is computed as a **local estimate** from the known swarm `S`. It is not globally authoritative. Different nodes may compute different scarcity values.

**A5.** Communication between the announcer and bidders is possible but unreliable. Bids may be lost. Not all eligible nodes may receive the announcement.

**A6.** The bid collection window `Δt_bid` is finite. The announcer must decide based on bids received within the window, even if not all eligible nodes responded.

**A7.** Weights `w_exec, w_energy, w_scarcity, w_comm` are mission-level parameters configured before deployment. They are not self-tuning in this version of the algorithm.

**A8.** Tasks are allocated to **single nodes** in this algorithm. Coalition-based execution is handled by Algorithm 005 and is outside scope here.

**A9.** The algorithm operates in a single allocation round. Re-allocation and preemption are handled by Algorithm 006 (graceful degradation).

**A10.** The meaningful capability threshold `θ_d` may vary by dimension. For binary capabilities (e.g., thermal sensor present/absent), `θ_d` may be set to a low non-zero value like 0.1. For continuous capabilities (e.g., compute), `θ_d` may be higher.

---

## 4. INPUTS

### Per invocation (at the announcer)

| Input | Source | Description |
|-------|--------|-------------|
| `τ_j` | Task discovery or mission plan | The task to be allocated |
| `R_j` | Algorithm 002 | Task requirement state (required dims, preferred dims, priority) |
| `E_j` | Algorithm 003 | Set of eligible nodes for `τ_j` |
| `q(n_i, τ_j)` for each `n_i ∈ E_j` | Algorithm 003 | Match quality per eligible node |

### Per invocation (at each bidder `n_i`)

| Input | Source | Description |
|-------|--------|-------------|
| `TaskAnnouncement(τ_j)` | Received message | Task ID, requirements `R_j`, priority `p_j`, announcer ID |
| `C_i` | Local measurement | Own capability state |
| `e_i` | Local measurement | Own energy state |
| `S` | Local knowledge | Set of known nodes (from recent capability reports) |
| `{C_k : k ∈ S}` | Received reports | Last-known capability states of other nodes |

### Configuration (mission-level)

| Parameter | Description |
|-----------|-------------|
| `w_exec, w_energy, w_scarcity, w_comm` | System cost weights |
| `θ_d` per dimension `d` | Meaningful capability threshold |
| `Δt_bid` | Bid collection window duration |
| `max_retries` | Maximum re-announcement attempts on assignment failure |

---

## 5. LOCALLY AVAILABLE INFORMATION

This section classifies every piece of information used by the algorithm according to the HESK observability model (Construction Guide, Problem 5).

### KNOWN (directly measured or locally stored)

- Own capability state `C_i` — from local sensor/hardware readings
- Own energy state `e_i` — from local battery measurement
- Own current task load — from local task list
- Own node identifier — from local configuration
- Bid collection window `Δt_bid` — from mission configuration
- System cost weights `w_exec, w_energy, w_scarcity, w_comm` — from mission configuration
- Meaningful capability thresholds `θ_d` — from mission configuration

### RECEIVED (from messages, with provenance)

- Other nodes' capability reports `{C_k : k ∈ S \ {i}}` — from periodic heartbeat/capability broadcasts. Each report carries a source ID and a logical timestamp. Staleness is bounded by heartbeat interval.
- Task announcement `TaskAnnouncement(τ_j)` — from the announcer node. Contains task requirements, priority, announcer ID.
- Assignment message — from the announcer, if this node wins the bid.
- Rejection message — from the announcer, if this node loses the bid.

### INFERRED (computed from known + received)

- Locally-known swarm `S` — the set of nodes from which a recent capability report has been received, plus self.
- Scarcity `σ_d(S)` for each dimension `d` — computed from capability reports in `S`.
- Execution cost — estimated from own capability state and task requirements.
- Scarcity penalty — computed from scarcity values and own non-required capabilities.
- System cost — weighted combination of the above.

### UNKNOWN (cannot be determined locally)

- Future tasks that have not yet been discovered or announced.
- Capability states of nodes that are unreachable or have not recently reported.
- True global swarm membership (nodes beyond communication range).
- Other nodes' bids (until received, if the node is the announcer).
- Whether the announcer received this node's bid (message may be lost).
- Exact future energy trajectory of other nodes.
- Whether a non-responding node is dead, partitioned, or simply slow.

---

## 6. OUTPUT

### Primary output: Assignment decision

The algorithm produces a single **assignment** binding a task to a node:

```
Assignment(τ_j) → n* ∈ E_j
```

where `n*` is the eligible node with the lowest system cost (tiebroken by highest match quality).

### Output data structure

```
AllocationResult {
    task_id:          TaskID          -- the allocated task
    assigned_node:    NodeID          -- the winning bidder
    system_cost:      float           -- the winning bid's system cost
    match_quality:    float           -- the winning bid's match quality (from 003)
    runner_up_node:   NodeID | None   -- second-best bidder (for fast re-assignment)
    runner_up_cost:   float | None    -- second-best system cost
    bids_received:    int             -- number of bids collected
    bids_expected:    int             -- |E_j| (may exceed bids_received)
    decision_trace:   DecisionTrace   -- full audit trail (see Section 8)
}
```

### Decision trace (for explainability, per Construction Guide Problem 25)

```
DecisionTrace {
    task_id:        TaskID
    announcer:      NodeID
    timestamp:      LogicalClock
    eligible_count: int
    bids: [
        BidRecord {
            node_id:          NodeID
            exec_cost:        float
            energy_cost:      float
            scarcity_penalty: float
            comm_cost:        float
            system_cost:      float
            match_quality:    float
            cap_snapshot:     CapState
        }
    ]
    winner:         NodeID
    reason:         string    -- human-readable explanation
}
```

---

## 7. DECISION RULE

### 7.1 Scarcity computation

The scarcity of dimension `d` across the locally-known swarm `S` is:

```
σ_d(S) = 1 − (|{n_k ∈ S : c_{k,d} ≥ θ_d}| / |S|)
```

**Interpretation:**
- `σ_d = 0` → every known node has meaningful capability on dimension `d` (not scarce)
- `σ_d = 1` → no known node has meaningful capability on dimension `d` (maximally scarce; this implies the current node also lacks it, or is the sole possessor)
- `σ_d = 0.8` → only 20% of known nodes have meaningful capability on `d`

**Properties:**
- Domain: `σ_d ∈ [0, 1]`
- Monotonic: removing a capable node from `S` increases `σ_d`
- Local: different nodes with different `S` may compute different values
- If `|S| = 1` (only self): `σ_d = 0` if self has `d`, `σ_d = 1` if self lacks `d`

### 7.2 Execution cost

The base execution cost estimates how expensive it is for node `n_i` to perform task `τ_j`:

```
exec_cost(n_i, τ_j) = Σ_{d ∈ D_j^req} max(0, r_{j,d} − c_{i,d}) / |D_j^req|
                     + (1 − e_i) × energy_factor
```

**First term:** average capability shortfall across required dimensions. For eligible nodes (who passed 003), this is typically small but nonzero for nodes that barely meet requirements.

**Second term:** energy penalty. Nodes with lower energy are more expensive to use. The `energy_factor` is a scaling constant (default 1.0).

A simpler V1 formulation that implementations may prefer:

```
exec_cost(n_i, τ_j) = 1 − q(n_i, τ_j) + (1 − e_i)
```

This reuses the match quality from Algorithm 003 directly. Higher quality → lower execution cost. Lower energy → higher execution cost.

### 7.3 Energy cost

```
energy_cost(n_i, τ_j) = estimated_energy_consumption(τ_j) / e_i
```

When `e_i` is low, the cost of consuming the same absolute energy is proportionally higher (the node is closer to depletion). If energy estimation is unavailable, a constant task-class energy cost may be used.

**Guard:** If `e_i < e_critical` (critically low energy), the node should not bid at all (this is enforced at the eligibility level in Algorithm 003, not here).

### 7.4 Scarcity penalty

The scarcity penalty for assigning node `n_i` to task `τ_j`:

```
scarcity_penalty(n_i, τ_j, S) = Σ_{d ∈ D \ D_j^req} [σ_d(S) × I(c_{i,d} ≥ θ_d)]
```
Where `I(c_{i,d} ≥ θ_d)` is an indicator function returning 1 if the capability meets the meaningful threshold, and 0 otherwise.

**Interpretation:** For every capability dimension that the **task does NOT require**, if node `n_i` has a meaningful level of that capability AND that capability is scarce in the swarm, there is a penalty. The penalty is proportional to:
1. How scarce the dimension is (`σ_d`) — rarer capabilities incur larger penalties

*Why use an indicator function instead of raw capability multiplication?* Multiplying by the raw capability value assumes a linear scale across all dimension types, which fails for categorical variables, capacities with different units, or inverted dimensions. Normalizing relative to the threshold ensures a mathematically sound penalty.

**Critical insight:** If the task DOES require dimension `d`, then using node `n_i`'s capability on `d` is not waste — it is productive use. Only non-required dimensions contribute to the penalty.

**Example:** Node A has a functioning thermal sensor (scarce, `σ_thermal = 0.8`). The task does not require thermal. The indicator `I(thermal ≥ θ_thermal)` evaluates to 1. Scarcity penalty contribution from thermal: `0.8 × 1 = 0.8`. This makes A more expensive to assign to this task, preserving A for future thermal-requiring tasks.

### 7.5 Communication cost

```
comm_cost(n_i, τ_j, announcer) = 1 − link_quality(n_i, announcer)
```

If link quality information is unavailable, use a default of 0 (assume good link). Communication cost penalizes assignments where the assigned node has poor communication with the announcer, which may impede result delivery and status reporting.

### 7.6 System cost (objective function)

The total system cost for assigning node `n_i` to task `τ_j`:

```
SYSTEM_COST(n_i, τ_j, S) = w_exec    × exec_cost(n_i, τ_j)
                          + w_energy  × energy_cost(n_i, τ_j)
                          + w_scarcity × scarcity_penalty(n_i, τ_j, S)
                          + w_comm    × comm_cost(n_i, τ_j, announcer)
```

All component costs are non-negative. The weights allow mission-specific tuning:
- High `w_scarcity` → system strongly preserves scarce capabilities
- High `w_exec` → system favors best immediate executor
- High `w_energy` → system favors energy-rich nodes
- High `w_comm` → system favors well-connected nodes

### 7.7 Bid selection rule

Given a set of received bids `B_j = {bid_1, bid_2, …, bid_m}` for task `τ_j`:

```
n* = argmin_{n_i ∈ bidders} SYSTEM_COST(n_i, τ_j, S)
```

**Tiebreak:** If two bids have equal system cost (within floating-point tolerance ε = 1e-6):

```
n* = argmax_{tied nodes} q(n_i, τ_j)
```

Select the node with higher match quality.

**Second tiebreak:** If match quality is also equal, select the node with higher energy `e_i` (preserve operational margin).

**Final tiebreak:** If all above are equal, select the node with the lower node ID (deterministic, reproducible).

### 7.8 Bidding protocol state machine

The allocation follows a modified Contract Net Protocol with six phases:

```
┌─────────────────────────────────────────────────────────────────┐
│                    ANNOUNCER STATE MACHINE                      │
│                                                                 │
│  IDLE ──[task discovered]──▶ ANNOUNCING                        │
│                                  │                              │
│                         [broadcast TaskAnnouncement]            │
│                                  │                              │
│                                  ▼                              │
│                           COLLECTING ──[Δt_bid expires]──▶ EVALUATING │
│                           (receive bids)                        │
│                                                    │            │
│                                          [select winner]        │
│                                                    │            │
│                                                    ▼            │
│                                              ASSIGNING          │
│                                           [send Assignment]     │
│                                           [send Rejections]     │
│                                                    │            │
│                                    ┌───────────────┤            │
│                            [Ack received]   [timeout / Reject]  │
│                                    │               │            │
│                                    ▼               ▼            │
│                                COMPLETED     REASSIGNING        │
│                                           [try runner-up or     │
│                                            re-announce]         │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│                     BIDDER STATE MACHINE                        │
│                                                                 │
│  IDLE ──[TaskAnnouncement received]──▶ EVALUATING              │
│                                            │                    │
│                              [check eligibility (003)]          │
│                              [compute system cost]              │
│                                            │                    │
│                                 ┌──────────┴──────────┐         │
│                           [eligible]            [not eligible]  │
│                                 │                     │         │
│                                 ▼                     ▼         │
│                            BIDDING               SILENT         │
│                       [send Bid msg]             (no action)    │
│                                 │                               │
│                      ┌──────────┴──────────┐                    │
│                [Assignment]          [Rejection / timeout]      │
│                      │                     │                    │
│                      ▼                     ▼                    │
│                 EXECUTING              IDLE                     │
│             [send Ack, begin task]                               │
└─────────────────────────────────────────────────────────────────┘
```

### Protocol messages

| Message | Sender | Receiver | Contents |
|---------|--------|----------|----------|
| `TaskAnnouncement` | Announcer | Broadcast | `{task_id, R_j, p_j, announcer_id, deadline}` |
| `Bid` | Bidder | Announcer | `{task_id, node_id, system_cost, match_quality, cap_snapshot, energy}` |
| `Assignment` | Announcer | Winner | `{task_id, node_id, assignment_timestamp}` |
| `Rejection` | Announcer | Losers | `{task_id, node_id}` |
| `Ack` | Winner | Announcer | `{task_id, node_id, commitment_confirmed}` |
| `Reject` | Winner | Announcer | `{task_id, node_id, reason}` (winner declines, e.g., state changed) |

---

## 8. PLAIN-ENGLISH ALGORITHM

### From the announcer's perspective:

1. A task `τ_j` is discovered or arrives from the mission plan.
2. Algorithm 002 provides the task requirement state `R_j`.
3. Algorithm 003 determines the eligible set `E_j` and match quality per node.
4. If `|E_j| = 0`, the task cannot be executed. Report failure upward. Stop.
5. If `|E_j| = 1`, the single eligible node is the only option. Skip bidding. Directly assign and await Ack.
6. If `|E_j| ≥ 2`, construct and broadcast a `TaskAnnouncement` to all reachable nodes.
7. Start the bid collection timer (`Δt_bid`).
8. Collect incoming `Bid` messages. Each bid contains the bidder's self-assessed system cost, match quality, and capability snapshot.
9. When `Δt_bid` expires, stop collecting.
10. If zero bids were received, re-announce up to `max_retries` times. If still zero, report allocation failure. Stop.
11. Evaluate all received bids. Select the bid with the lowest `SYSTEM_COST`. Tiebreak by highest `match_quality`, then highest `energy`, then lowest `node_id`.
12. Send `Assignment` to the winner. Send `Rejection` to all other bidders.
13. Record the runner-up (second-lowest cost bidder) for fast re-assignment.
14. Wait for `Ack` from the winner within a timeout.
15. If `Ack` received: allocation complete. Record the decision trace.
16. If `Reject` received or timeout: assign to the runner-up. If no runner-up, re-announce (decrement retries).

### From a bidder's perspective:

1. Receive `TaskAnnouncement(τ_j)`.
2. Run Algorithm 003 locally to check eligibility. If not eligible, remain silent.
3. Compute `exec_cost(self, τ_j)` from own capability state.
4. Compute `energy_cost(self, τ_j)` from own energy state.
5. Compute `scarcity_penalty(self, τ_j, S)` from known swarm capabilities.
6. Compute `comm_cost(self, τ_j, announcer)` from link quality to announcer.
7. Compute `SYSTEM_COST(self, τ_j, S)` as the weighted sum.
8. Construct and send `Bid` message to the announcer.
9. Wait for `Assignment` or `Rejection`.
10. If `Assignment` received and node state has not materially changed since bidding: send `Ack`, begin execution.
11. If `Assignment` received but node state has materially changed (e.g., energy dropped critically, new task preempted capacity): send `Reject` with reason.
12. If `Rejection` received or timeout: return to idle.

---

## 9. PSEUDOCODE

### 9.1 Scarcity computation

```
function compute_scarcity(d: Dimension, S: Set<Node>, θ_d: float) → float:
    """Compute scarcity of dimension d across locally-known swarm S."""
    if |S| == 0:
        return 1.0  -- no information → assume maximally scarce
    
    count_meaningful = 0
    for each n_k in S:
        if c_{k,d} >= θ_d:
            count_meaningful += 1
    
    σ_d = 1.0 - (count_meaningful / |S|)
    return σ_d
```

### 9.2 Execution cost

```
function compute_exec_cost(n_i: Node, τ_j: Task) → float:
    """Estimate execution cost using match quality from 003."""
    quality = q(n_i, τ_j)           -- from Algorithm 003
    energy_penalty = 1.0 - e_i      -- low energy → high penalty
    return (1.0 - quality) + energy_penalty
```

### 9.3 Energy cost

```
function compute_energy_cost(n_i: Node, τ_j: Task) → float:
    """Energy cost inversely proportional to remaining energy."""
    if e_i <= 0.0:
        return INFINITY              -- should not bid (003 should exclude)
    base_consumption = task_energy_estimate(τ_j)  -- constant per task class
    return base_consumption / e_i
```

### 9.4 Scarcity penalty

```
function compute_scarcity_penalty(n_i: Node, τ_j: Task, S: Set<Node>) → float:
    """Penalize wasting scarce capabilities on non-requiring tasks."""
    penalty = 0.0
    D_req = required_dimensions(τ_j)
    
    for each d in D:
        if d in D_req:
            continue                 -- productive use, no penalty
        
        # Only penalize if the node has a MEANINGFUL level of this capability
        if c_{i,d} >= θ_d:
            σ_d = compute_scarcity(d, S, θ_d)
            penalty += σ_d           -- add scarcity penalty (normalized, no raw multiplication)
    
    return penalty
```

### 9.5 System cost

```
function compute_system_cost(n_i: Node, τ_j: Task, S: Set<Node>) → float:
    """Compute total system cost for assigning n_i to τ_j."""
    cost  = w_exec     * compute_exec_cost(n_i, τ_j)
    cost += w_energy   * compute_energy_cost(n_i, τ_j)
    cost += w_scarcity * compute_scarcity_penalty(n_i, τ_j, S)
    cost += w_comm     * compute_comm_cost(n_i, τ_j, announcer)
    return cost
```

### 9.6 Bid construction (at bidder)

```
function construct_bid(n_i: Node, τ_j: Task, S: Set<Node>) → Bid | None:
    """Construct a bid if eligible, else return None."""
    if not is_eligible(n_i, τ_j):    -- Algorithm 003 check
        return None
    
    sys_cost = compute_system_cost(n_i, τ_j, S)
    quality  = q(n_i, τ_j)
    
    return Bid {
        task_id:      τ_j.id,
        node_id:      n_i.id,
        system_cost:  sys_cost,
        match_quality: quality,
        cap_snapshot:  C_i,           -- current capability state
        energy:       e_i
    }
```

### 9.7 Bid evaluation (at announcer)

```
function evaluate_bids(bids: List<Bid>, τ_j: Task) → AllocationResult:
    """Select winner from collected bids."""
    if |bids| == 0:
        return AllocationResult.FAILURE
    
    -- Sort: primary = lowest system_cost, tiebreak = highest quality,
    --       then highest energy, then lowest node_id
    sorted_bids = sort(bids, key = (
        +bid.system_cost,      -- ascending
        -bid.match_quality,    -- descending
        -bid.energy,           -- descending
        +bid.node_id           -- ascending (deterministic)
    ))
    
    winner    = sorted_bids[0]
    runner_up = sorted_bids[1] if |sorted_bids| >= 2 else None
    
    return AllocationResult {
        task_id:        τ_j.id,
        assigned_node:  winner.node_id,
        system_cost:    winner.system_cost,
        match_quality:  winner.match_quality,
        runner_up_node: runner_up.node_id if runner_up else None,
        runner_up_cost: runner_up.system_cost if runner_up else None,
        bids_received:  |bids|,
        bids_expected:  |E_j|,
        decision_trace: build_trace(τ_j, bids, winner)
    }
```

### 9.8 Full announcer protocol

```
function announce_and_allocate(τ_j: Task, E_j: Set<Node>) → AllocationResult:
    """Full announcer-side allocation protocol."""
    retries = max_retries
    
    while retries > 0:
        broadcast(TaskAnnouncement(τ_j))
        bids = collect_bids(τ_j, timeout = Δt_bid)
        
        if |bids| == 0:
            retries -= 1
            continue
        
        result = evaluate_bids(bids, τ_j)
        send(Assignment(τ_j, result.assigned_node))
        
        for bid in bids:
            if bid.node_id != result.assigned_node:
                send(Rejection(τ_j, bid.node_id))
        
        response = await_ack(result.assigned_node, timeout = Δt_ack)
        
        if response == ACK:
            return result  -- success
        
        if response == REJECT or response == TIMEOUT:
            -- Try runner-up without re-announcing
            if result.runner_up_node is not None:
                send(Assignment(τ_j, result.runner_up_node))
                response2 = await_ack(result.runner_up_node, timeout = Δt_ack)
                if response2 == ACK:
                    result.assigned_node = result.runner_up_node
                    return result
            
            retries -= 1
            continue
    
    return AllocationResult.FAILURE
```

---

## 10. WORKED EXAMPLE

### Scenario: The thermal drone problem

This example demonstrates why scarcity-aware allocation produces better system-level outcomes than naive cost-minimizing allocation.

### Setup

**Swarm:** 5 nodes, `S = {A, B, C, D, E}`

| Node | thermal | rgb | compute | lidar | energy |
|------|---------|-----|---------|-------|--------|
| A    | 0.95    | 0.80| 0.60    | 0.00  | 0.70   |
| B    | 0.00    | 0.85| 0.70    | 0.50  | 0.80   |
| C    | 0.00    | 0.75| 0.90    | 0.00  | 0.65   |
| D    | 0.00    | 0.60| 0.40    | 0.80  | 0.90   |
| E    | 0.00    | 0.70| 0.55    | 0.00  | 0.75   |

**Task:** `τ_map` — Visual mapping of Zone B

```
R_map = {
    required: { rgb: 0.6 },
    preferred: { compute: 0.5 },
    mission_priority: 0.7
}
D_map^req = {rgb}
```

**Configuration:**
- `θ_d = 0.1` for all dimensions (binary-like threshold)
- `w_exec = 1.0, w_energy = 0.5, w_scarcity = 2.0, w_comm = 0.0` (communication cost ignored for clarity)

### Step 1: Eligibility (from Algorithm 003)

All nodes with `rgb ≥ 0.6` are eligible: `E_map = {A, B, C, D, E}`

All five nodes satisfy the required capability threshold.

### Step 2: Scarcity computation

Each bidding node computes scarcity for all dimensions using the full known swarm:

**σ_thermal:**
- Nodes with `thermal ≥ 0.1`: only A
- `σ_thermal = 1 − (1/5) = 0.80`

**σ_rgb:**
- Nodes with `rgb ≥ 0.1`: A, B, C, D, E (all five)
- `σ_rgb = 1 − (5/5) = 0.00`

**σ_compute:**
- Nodes with `compute ≥ 0.1`: A, B, C, D, E (all five)
- `σ_compute = 1 − (5/5) = 0.00`

**σ_lidar:**
- Nodes with `lidar ≥ 0.1`: B, D (two nodes)
- `σ_lidar = 1 − (2/5) = 0.60`

### Step 3: Bid computation for Node A (thermal drone)

**Exec cost:** Using `q(A, τ_map) = 0.80` (good rgb match)
```
exec_cost(A) = (1 - 0.80) + (1 - 0.70) = 0.20 + 0.30 = 0.50
```

**Energy cost:** Using `base_consumption = 0.1`
```
energy_cost(A) = 0.1 / 0.70 = 0.143
```

**Scarcity penalty:** Non-required dimensions for A: {thermal, compute, lidar}
```
thermal contribution:  σ_thermal × c_{A,thermal} = 0.80 × 0.95 = 0.760
compute contribution:  σ_compute × c_{A,compute} = 0.00 × 0.60 = 0.000
lidar contribution:    σ_lidar   × c_{A,lidar}   = 0.60 × 0.00 = 0.000
─────────────────────────────────────────────────────────────────
scarcity_penalty(A) = 0.760
```

**System cost for A:**
```
SYSTEM_COST(A) = 1.0 × 0.50 + 0.5 × 0.143 + 2.0 × 0.760 + 0.0
               = 0.500 + 0.071 + 1.520
               = 2.091
```

### Step 4: Bid computation for Node B (standard drone)

**Exec cost:** Using `q(B, τ_map) = 0.85`
```
exec_cost(B) = (1 - 0.85) + (1 - 0.80) = 0.15 + 0.20 = 0.35
```

**Energy cost:**
```
energy_cost(B) = 0.1 / 0.80 = 0.125
```

**Scarcity penalty:** Non-required dimensions for B: {thermal, compute, lidar}
```
thermal contribution:  0.80 × 0.00 = 0.000
compute contribution:  0.00 × 0.70 = 0.000
lidar contribution:    0.60 × 0.50 = 0.300
─────────────────────────────────────────
scarcity_penalty(B) = 0.300
```

**System cost for B:**
```
SYSTEM_COST(B) = 1.0 × 0.35 + 0.5 × 0.125 + 2.0 × 0.300 + 0.0
               = 0.350 + 0.063 + 0.600
               = 1.013
```

### Step 5: Bid computation summary

| Node | exec_cost | energy_cost | scarcity_penalty | SYSTEM_COST | match_quality |
|------|-----------|-------------|------------------|-------------|---------------|
| A    | 0.500     | 0.143       | 0.760            | **2.091**   | 0.80          |
| B    | 0.350     | 0.125       | 0.300            | **1.013**   | 0.85          |
| C    | 0.600     | 0.154       | 0.000            | **0.677**   | 0.75          |
| D    | 0.700     | 0.111       | 0.480            | **1.016**   | 0.60          |
| E    | 0.550     | 0.133       | 0.000            | **0.617**   | 0.70          |

### Step 6: Winner selection

Sorted by SYSTEM_COST (ascending):

1. **E: 0.617** ← winner
2. C: 0.677
3. B: 1.013
4. D: 1.016
5. A: 2.091

**Winner: Node E.** Runner-up: Node C.

### Step 7: Why this is correct

- **Node A** had the **second-best raw match quality** (rgb=0.80) and decent execution cost. A naive allocator might select A.
- But A is the **only thermal-capable node** in the swarm. Assigning A to a non-thermal task wastes that scarce capability.
- The scarcity penalty `0.760` correctly inflated A's system cost to `2.091`, making it the **most expensive** option.
- **Node E** has no scarce capabilities (no thermal, no lidar) and reasonable rgb. Its scarcity penalty is `0.000`.
- The allocation **preserves Node A's thermal capability** for future thermal-requiring tasks.

### What a naive allocator would do

A cost-minimizer ignoring scarcity would rank by `exec_cost` alone:

1. B: 0.350
2. A: 0.500
3. E: 0.550

Node B would win. Node B has lidar (moderately scarce, `σ=0.6`), so this is less wasteful than choosing A, but still ignores scarcity. A random allocator might select A with probability 1/5, wasting the only thermal node 20% of the time.

---

## 11. EDGE CASES

### EC1: Only one eligible node

**Condition:** `|E_j| = 1`

**Handling:** Skip bidding. Directly assign the sole eligible node. No scarcity comparison is meaningful with a single option — there is no choice to optimize.

**Risk:** The sole eligible node may have scarce capabilities that are being consumed. This is unavoidable — no alternative executor exists. Log the assignment with a warning in the decision trace.

### EC2: All eligible nodes have identical scarcity profiles

**Condition:** For all `n_i, n_k ∈ E_j` and for all `d ∈ D`: `c_{i,d} = c_{k,d}`

**Handling:** Scarcity penalties are identical. Selection falls through to execution cost and energy tiebreakers. This is correct — when no node is more scarce than another, pure execution efficiency should dominate.

### EC3: Announcer disconnects during bid collection

**Condition:** The announcer node becomes unreachable after broadcasting `TaskAnnouncement` but before evaluating bids.

**Handling:**
- Bidders submit bids to the announcer. Bids are lost (no recipient).
- Bidders timeout waiting for `Assignment` / `Rejection` and return to idle.
- The task is orphaned. No assignment occurs.
- **Recovery:** Another node must detect that `τ_j` remains unassigned (via task status monitoring in Algorithm 006) and re-announce.

**Invariant preserved:** No node executes a task it was not explicitly assigned. The system fails safe (no assignment) rather than producing conflicting assignments.

### EC4: All bids arrive after Δt_bid expires

**Condition:** Network latency causes all bids to arrive after the collection window closes.

**Handling:**
- Announcer evaluates with zero bids.
- Re-announces up to `max_retries` times.
- If the problem is persistent, consider increasing `Δt_bid` (but this is a configuration change, not an algorithmic one).
- Late-arriving bids are discarded. The announcer does not process bids after transitioning to EVALUATING state.

**Design note:** `Δt_bid` should be calibrated to the expected network round-trip time. Setting it too short wastes re-announcement bandwidth. Setting it too long delays allocation.

### EC5: Winner crashes before sending Ack

**Condition:** Announcer sends `Assignment` to winner. Winner crashes. No `Ack` arrives.

**Handling:**
- Announcer times out waiting for `Ack`.
- Announcer assigns to the runner-up (if one was recorded).
- If runner-up also fails or was not recorded, re-announce.
- The crashed winner, if it recovers, must not begin executing because it never confirmed the assignment. Assignment without Ack is not a commitment.

**Invariant preserved:** A node only begins task execution after sending `Ack`. No silent unconfirmed execution.

### EC6: Scarcity of 1.0 (maximally scarce, nobody has it)

**Condition:** `σ_d = 1.0` for some dimension `d`.

**Meaning:** No node in the locally-known swarm has meaningful capability on dimension `d`. This can occur if:
- The only capable node left the swarm or failed.
- The node computing scarcity has stale information.

**Impact on allocation:** If no node has `c_{i,d} ≥ θ_d`, then `c_{i,d}` is near zero for all nodes, so `σ_d × c_{i,d} ≈ 0`. The high scarcity value has no practical effect because no node's penalty increases. The formula is self-correcting.

### EC7: Scarcity of 0.0 (abundant, everyone has it)

**Condition:** `σ_d = 0.0` for some dimension `d`.

**Meaning:** Every known node has meaningful capability on `d`. Using any node's `d` capability is not wasteful.

**Impact:** The `σ_d × c_{i,d}` term is zero regardless of `c_{i,d}`. No scarcity penalty. Correct behavior — there is no opportunity cost when the capability is abundant.

### EC8: Task requires ALL capability dimensions

**Condition:** `D_j^req = D` (the task requires every known dimension).

**Impact:** `D \ D_j^req = ∅`. The scarcity penalty sum has zero terms. `scarcity_penalty = 0.0` for all nodes.

**Correctness:** If the task requires the node's scarce capabilities, using them is not waste — it is productive. The algorithm correctly imposes no scarcity penalty.

### EC9: Bid with stale capability data

**Condition:** A bidder computes its bid, but between bid submission and evaluation, its capability state changes (e.g., sensor fails, energy drops).

**Handling:** The `Ack/Reject` mechanism handles this. When the winner receives `Assignment`, it re-checks its current state. If it can no longer execute, it sends `Reject` with a reason. The announcer falls back to the runner-up.

The bid's `cap_snapshot` lets the announcer detect gross staleness, but the primary safety mechanism is the bidder's own honest Ack/Reject decision.

---

## 12. FAILURE MODES

### FM1: Systematic scarcity mis-estimation

**Cause:** A node's locally-known swarm `S` is much smaller than the true swarm (due to partitions). The node overestimates scarcity because it cannot see distant capable nodes.

**Effect:** Scarcity penalties are inflated. The algorithm becomes overly conservative, avoiding capable nodes that aren't actually scarce.

**Mitigation:** Accept this as inherent to local-information operation. A node that knows only 3 nodes and sees only 1 thermal node correctly assigns high scarcity **from its perspective**. When the partition heals and more capability reports arrive, scarcity estimates self-correct.

**Design principle:** Overestimating scarcity (being too conservative) is safer than underestimating it (wasting truly scarce capabilities). The asymmetry is acceptable.

### FM2: Weight misconfiguration

**Cause:** Mission weights are poorly chosen. Example: `w_scarcity = 100, w_exec = 0.01`.

**Effect:** The algorithm almost exclusively optimizes for scarcity, ignoring execution quality. Tasks may be assigned to weak executors simply because they have no scarce capabilities.

**Mitigation:** Provide recommended weight ranges in documentation. Validate that no weight is more than 10× any other weight (configurable sanity check, not a hard constraint). Log warnings if the winning bid has very low match quality.

### FM3: Dominant node problem

**Cause:** One node has high capabilities across many dimensions AND all those dimensions are scarce. Its scarcity penalty is high for ALL non-trivial tasks.

**Effect:** The node is never assigned any task because every assignment would waste some scarce capability. The node sits idle while the swarm is overloaded.

**Mitigation:** When the task REQUIRES the scarce capability, the scarcity penalty for that dimension is zero (Section 7.4). The node should correctly win bids for tasks that need its specific scarce capabilities. For tasks that don't need its capabilities, it correctly loses — this is the intended behavior. If the node is idle and the swarm is overloaded, Algorithm 006 (degradation) may override and assign it anyway.

### FM4: Bid message loss

**Cause:** Network unreliability causes some bids to never reach the announcer.

**Effect:** The announcer evaluates a subset of bids. The globally optimal winner may not have submitted a bid (or its bid was lost).

**Mitigation:** The algorithm cannot guarantee global optimality under message loss. It guarantees optimality **among received bids**. Re-announcement with retries provides probabilistic coverage. The system is designed for "good enough" allocation under partial information, not guaranteed global optimality.

### FM5: Announcer bias

**Cause:** The announcer evaluates bids and selects the winner. A malicious or buggy announcer could always assign tasks to itself or a preferred node.

**Mitigation:** HESK v1 assumes non-adversarial nodes. The decision trace provides transparency — any node can audit the announcer's selection by examining the trace. Future versions may implement distributed bid verification.

### FM6: Stale capability reports inflating scarcity

**Cause:** A capable node fails silently. Other nodes continue to count it in scarcity calculations (as a capable node), underestimating scarcity.

**Effect:** Scarcity appears lower than reality. The algorithm is less protective of truly scarce capabilities.

**Mitigation:** Capability reports carry timestamps. Reports older than a staleness threshold (e.g., 3× heartbeat interval) should be excluded from the scarcity calculation's node set `S`. A node with a stale report is treated as "unknown" rather than "capable."

---

## 13. INVARIANTS

**INV-1: Local information only.** Scarcity `σ_d(S)` is computed exclusively from locally-known capability reports and self-measurement. No algorithm step accesses global simulation truth. (HESK Invariant 1, 2)

**INV-2: No central coordinator required.** Any node can serve as announcer for any task. There is no permanent allocation manager. If the announcer fails, another node can re-announce. (HESK Invariant 3)

**INV-3: Scarcity penalty does not penalize productive use.** If `d ∈ D_j^req` (the task requires dimension `d`), then dimension `d` contributes zero to the scarcity penalty. Only non-required dimensions incur penalty.

**INV-4: System cost is non-negative.** All component costs are non-negative. All weights are non-negative. Therefore `SYSTEM_COST ≥ 0` for all inputs.

**INV-5: Deterministic winner selection.** Given the same set of bids, the same winner is always selected. The multi-level tiebreak (cost → quality → energy → node_id) eliminates ambiguity.

**INV-6: Assignment requires Ack.** A node does not begin task execution until it has sent `Ack` to the announcer. An `Assignment` message alone does not constitute commitment. This prevents orphaned partial executions when the winner crashes before confirming.

**INV-7: Scarcity is bounded.** `σ_d ∈ [0, 1]` for all dimensions and swarm states. It equals `0.0` when all nodes have meaningful `d`, equals `1.0` when no nodes have meaningful `d`.

**INV-8: Bid evaluation is transparent.** Every allocation decision produces a `DecisionTrace` containing all received bids, their component costs, the winner, and a human-readable reason string. (Construction Guide, Problem 25)

**INV-9: No bid fabrication.** The announcer evaluates only bids that were actually received as messages. It does not infer or fabricate bids for non-responding nodes.

**INV-10: Physical capabilities remain attached to hardware.** The allocation algorithm assigns responsibility (task ownership), never transfers physical capabilities between nodes. (HESK Invariant 4, 5)

---

## 14. OPEN QUESTIONS

### OQ1: Weight setting

How should `w_exec, w_energy, w_scarcity, w_comm` be determined? Options:
- **Manual tuning** per mission profile (current approach).
- **Offline optimization** via simulation sweep to find Pareto-optimal weight vectors.
- **Adaptive weights** that shift based on swarm state (e.g., increase `w_scarcity` when the swarm shrinks).

Adaptive weights are more powerful but harder to reason about. V1 should use fixed weights; adaptive weights are a V2 research question.

### OQ2: Future option loss estimation

The current scarcity penalty captures **current** rarity but not **predicted future demand**. A thermal node's scarcity penalty is high even if no thermal task is expected.

Possible extensions:
- Maintain a task type histogram (what tasks have been announced recently).
- Weight scarcity by historical demand for that dimension.
- Use mission plan lookahead (if the mission plan is known and contains future thermal tasks, increase thermal scarcity weight).

**Danger:** Predicting future tasks accurately requires information that may not be available. Overfit prediction could be worse than the simple scarcity heuristic.

### OQ3: Distributed bid evaluation

Currently the announcer is a single evaluator. Can bid evaluation be distributed?

Options:
- **Redundant announcers:** Multiple nodes independently evaluate bids. They should converge on the same winner (deterministic tiebreak ensures this if they receive the same bids).
- **Consensus-based evaluation:** Announce bids publicly and have multiple nodes vote on the winner. High communication overhead.

For V1, single-announcer evaluation is sufficient. Redundancy is a robustness enhancement for V2.

### OQ4: Dominant node prevention

A node with many scarce capabilities may never be assigned to any task (see FM3). Should there be a mechanism to override scarcity protection when:
- The node has been idle for longer than a threshold?
- The swarm is critically overloaded?
- The task priority exceeds a threshold?

Possible: `if p_j > priority_override_threshold: w_scarcity = 0`. This disables scarcity protection for critical tasks. The mission accepts the opportunity cost.

### OQ5: Re-bidding cooldown

If a task is re-announced after a failed assignment, should previously-rejected bidders bid again? Should the announcer remember previous bids?

Current design: Re-announcement is a fresh round. All eligible nodes may bid again. Previous bids are discarded. This is simple but may cause thrashing if the same winner keeps failing.

Alternative: The announcer maintains a "rejected winners" list for the current task and excludes them from future rounds.

### OQ6: Interaction with Algorithm 005 (Coalition Formation)

This algorithm (004) assigns tasks to **single nodes**. Algorithm 005 handles coalitions. When should the system prefer a coalition over a single node?

Possible protocol:
1. Run 004 first. If a single-node assignment with acceptable system cost exists, use it.
2. If no single node's system cost is below a threshold, invoke 005 to seek a coalition.
3. Compare single-node best cost against coalition cost (which includes communication overhead).

The threshold and comparison mechanism are unresolved.

### OQ7: Scarcity across partitions

After a network partition, two sub-swarms compute scarcity independently. When they reconnect, their scarcity estimates diverge. How should scarcity be reconciled?

Simple approach: Upon reconnection, nodes exchange capability reports. Each node recomputes scarcity from the merged swarm `S`. No special reconciliation logic is needed — scarcity is a stateless function of the current `S`.

### OQ8: Non-linear scarcity

The current formula treats scarcity linearly: `σ_d = 1 − (count / |S|)`. Should scarcity be non-linear?

Example: The difference between 1 capable node and 2 capable nodes (redundancy) may be more important than the difference between 10 and 11. A logarithmic or exponential scarcity function might capture this.

Possible: `σ_d = 1 − (count / |S|)^α` where `α < 1` amplifies scarcity at low counts.

---

## 15. BASELINE FOR COMPARISON

### BASELINE A: Lowest execution cost (no scarcity awareness)

**Rule:** Among eligible nodes, assign to the node with the lowest `exec_cost(n_i, τ_j)`.

```
n* = argmin_{n_i ∈ E_j} exec_cost(n_i, τ_j)
```

**Behavior:** Selects the best immediate executor. Ignores scarcity entirely.

**Failure case (thermal drone):** In the worked example (Section 10), Baseline A would rank by `exec_cost`:
- B: 0.350
- A: 0.500
- E: 0.550
- C: 0.600
- D: 0.700

**Winner: Node B.** While B is not the thermal node, this is coincidental. If A had the best rgb sensor (`exec_cost(A) = 0.300`), Baseline A would select A, consuming the only thermal node on a non-thermal task. Over many tasks, Baseline A will eventually assign A whenever A is the cheapest executor, regardless of thermal scarcity.

**Expected degradation:** In a mission with both thermal and non-thermal tasks, Baseline A wastes thermal availability ~`1/|E_j|` of the time (when A happens to be cheapest). When a thermal task arrives later, A may be busy or energy-depleted.

### BASELINE B: Random eligible node (no optimization)

**Rule:** Among eligible nodes, select uniformly at random.

```
n* = random_choice(E_j)
```

**Behavior:** No cost reasoning. No scarcity reasoning. Pure random selection.

**Failure case (thermal drone):** Each eligible node is selected with probability `1/|E_j| = 1/5 = 0.20`. Node A (thermal) is assigned 20% of the time. Over a sequence of 10 non-thermal tasks, the expected number of times A is wastefully assigned is 2.0.

**Expected degradation:** Random assignment is strictly worse than both scarcity-aware allocation and cost-minimizing allocation. It wastes scarce capabilities at the base rate and also assigns poorly-matched nodes to tasks.

### Comparison metrics

| Metric | Baseline A | Baseline B | HESK 004 |
|--------|-----------|-----------|----------|
| Immediate exec cost | **Minimized** | Random | Near-minimum (slightly higher due to scarcity avoidance) |
| Scarce capability preservation | No protection | No protection | **Protected by scarcity penalty** |
| Future task success rate | Degrades as scarce nodes are consumed | Degrades faster | **Higher — scarce nodes available for future tasks** |
| Energy efficiency | Partial (via exec cost) | None | **Explicit energy weighting** |
| Communication awareness | None | None | **Explicit comm cost weighting** |
| Decision transparency | Low (single metric) | None | **Full decision trace** |

### Evaluation protocol

To demonstrate HESK 004's advantage over baselines:

1. Define a task sequence containing both general tasks (non-thermal) and specialist tasks (thermal-requiring).
2. Run the same task sequence under Baseline A, Baseline B, and HESK 004.
3. Measure:
   - **Mission utility preserved** — fraction of specialist tasks successfully assigned to a capable node.
   - **Scarce capability availability** — fraction of time the thermal node is available when a thermal task arrives.
   - **Total execution cost** — sum of `exec_cost` across all assigned tasks (HESK may be slightly higher per-task but achieves better system-level utility).
   - **Tasks failed due to capability exhaustion** — tasks that could not be assigned because the only capable node was busy with a non-requiring task.
4. Plot mission utility over time under progressive node loss (removing 1 node every N tasks) to show graceful degradation differences.

---

## 16. REFERENCES

1. Smith, R.G. "The Contract Net Protocol: High-Level Communication and Control in a Distributed Problem Solver." *IEEE Transactions on Computers*, C-29(12):1104-1113, 1980.
2. Gerkey, B.P. and Matarić, M.J. "A Formal Analysis and Taxonomy of Task Allocation in Multi-Robot Systems." *The International Journal of Robotics Research*, 23(9):939-954, 2004.
3. Koenig, S., Tovey, C., Zheng, X., and Sungur, I. "Sequential Bundle-Method Algorithms for Market-Based Multi-Robot Task Allocation." *IEEE International Conference on Robotics and Automation*, 2007.

---

*Algorithm 004 version 1.0. Dependencies: 001 (capability model), 002 (task model), 003 (capability matching). Consumed by: 005 (coalition formation), 006 (graceful degradation).*
