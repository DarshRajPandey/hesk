# 005 — Coalition Formation

> **Status:** v0.1 draft  
> **Depends on:** [001 Capability Model](./001_capability_model.md), [002 Task Model](./002_task_model.md), [003 Capability Matching](./003_capability_matching.md)  
> **Consumed by:** [006 Graceful Degradation](./006_graceful_degradation.md), [008 Partition Reconciliation](./008_partition_reconciliation.md)  
> **Prior art:** Coalition Formation in Multi-Agent Systems [Shehory & Kraus, 1998], Multi-Robot Task Allocation [Gerkey & Matarić, 2004]

---

## 1. PROBLEM

### 1.1 Core question

> When no single node n_i in the locally-known swarm S can satisfy a task τ_j's required capabilities (Algorithm 003 returns ineligible for all solo candidates), can a temporary coalition Γ ⊆ S of two or more nodes combine their capabilities to satisfy the task, and can they actually work together given real communication constraints?

### 1.2 Why coalitions are necessary in HESK

In a heterogeneous swarm, no individual node may possess every capability a complex task demands.  This is by design — heterogeneity means specialization.

**Example from HESK Scope §10:**

Task `mapping_zone_b` requires:
- camera ≥ 0.7
- localization ≥ 0.8
- compute ≥ 0.5

Available nodes after node loss:
- Drone B: camera = 0.9, localization = 0.9, compute = 0.2 (fails compute)
- Rover C: camera = 0.1, localization = 0.3, compute = 1.0 (fails camera, localization)

No solo node qualifies.  But B + C together cover all required dimensions — if they can communicate fast enough to exchange camera data for remote processing.

### 1.3 What makes this hard

A coalition is NOT a Python list of node IDs.  It is a **temporary distributed execution dependency**.

Three constraints that naive coalition formation ignores:

1. **Capability composition is type-dependent.**  You cannot simply add capability vectors.  Camera quality does not sum (two 0.4 cameras ≠ one 0.8 camera).  Compute capacity does sum.  Thermal sensing is boolean — one member having it is sufficient.

2. **Communication feasibility gates operational viability.**  A theoretically capable coalition whose members cannot exchange required data within latency and bandwidth constraints is useless (HESK Scope §10, Construction Guide Problem 14).

3. **Coalition overhead is real.**  Coordination messages, data serialization, synchronization delays, and the increased probability of member failure all add cost that solo execution does not bear.

### 1.4 Relationship to other algorithms

| Algorithm | Interaction |
|-----------|-------------|
| 003 Capability Matching | Coalition formation is triggered when 003 returns no eligible solo node for a task. |
| 004 Scarcity Allocation | Solo bids from 004 and coalition proposals from 005 may compete.  The final assignment decision is made by the calling context (typically 006). |
| 006 Graceful Degradation | Degradation may invoke coalition formation as an alternative to tier descent. |

---

## 2. DEFINITIONS

### 2.1 Shared notation

| Symbol | Meaning |
|--------|---------|
| n_i | Node i |
| C_i | Capability state of node i (from 001) |
| c_{i,d} | Node i's value for dimension d |
| τ_j | Task j |
| R_j | Requirement state of task j (from 002) |
| R_j^req | Required capabilities of τ_j |
| R_j^pref | Preferred capabilities of τ_j |
| π_j | Mission priority of τ_j |
| Γ | A coalition: set of node identifiers {n_a, n_b, ...} |
| C_Γ | Composed capability state of coalition Γ |
| q_{ij} | Communication link quality between nodes i and j ∈ [0, 1] |
| bw_{ij} | Estimated available bandwidth between nodes i and j (kbps) |
| lat_{ij} | Estimated one-way latency between nodes i and j (ms) |

### 2.2 Capability composition rules

Capability composition determines how a coalition's joint capability for a dimension d is derived from its members' individual values.  Composition is **semantics-dependent**.

| Composition Semantic | Rule | Rationale | Example |
|----------------------|------|-----------|---------|
| MAX | c_{Γ,d} = max_{m ∈ Γ} c_{m,d} | Quality or existence does not sum. The best member provides the capability. | camera_quality, thermal_sensor |
| SUM_DIVISIBLE | c_{Γ,d} = Σ_{m ∈ Γ} c_{m,d} | Quantities that can be partitioned across members without loss (less overhead). | vram_mb, disk_space |
| NON_COMPOSABLE | Cannot be aggregated | The task requires a single monolithic capability. | position, latency_critical_compute |
| UNION | c_{Γ,d} = ∪_{m ∈ Γ} c_{m,d} | Set of distinct options provided by members. | supported_runtimes |

The composition semantic is defined by the capability dimension itself, not just its data type (e.g., continuous variables could be MAX or NON_COMPOSABLE).

> **PROVISIONAL v0.1 CHOICE:** These composition rules are deliberately simple.  Known limitations:
> - CONTINUOUS = MAX assumes the best member can be the sole provider.  In reality, the provider of dimension d may be a different member than the provider of dimension d'.  The composition rule does not capture this — but communication feasibility checking partially addresses it by verifying data flow paths.
> - CAPACITY = SUM assumes all members' capacity is usable.  In reality, coordination overhead may consume some capacity.  v0.1 applies a flat overhead deduction (see §7).
> - Some dimensions may not compose at all (e.g., `position` — a coalition does not have a single position).  Non-composable dimensions are excluded from composition and are handled by role assignment within the coalition.

### 2.3 ComposedCapabilityState

The result of applying composition rules to a set of nodes:

```
ComposedCapabilityState:
  members:           [n_a, n_b, ...]            # member list
  composed_values:   {d: composed_c_{Γ,d}}      # per-dimension composed value
  provider_map:      {d: n_k}                   # which member provides each dimension
  composition_rules: {d: rule_type}             # which rule was applied
```

The `provider_map` is critical: it identifies which specific node in the coalition is responsible for each dimension.  This is used by communication feasibility checking (§2.5) and role assignment.

### 2.4 Coalition structure

```
Coalition:
  coalition_id:      string                     # unique identifier
  task_id:           string                     # the task this coalition serves
  members:           [NodeId]                   # participating nodes
  initiator:         NodeId                     # node that proposed the coalition
  role_assignment:   {NodeId: [dimension]}      # which member covers which dims
  composed_state:    ComposedCapabilityState     # joint capability
  data_flow_plan:    [DataFlowLink]             # how data moves between members
  estimated_cost:    float                      # total coalition cost
  formation_time:    float                      # wall time when formed
  status:            CoalitionStatus            # FORMING | ACTIVE | DEGRADED | DISSOLVED
```

### 2.5 Data flow feasibility

A task's `data_flow` requirements (from 002) specify what data must move between capabilities during execution:

```
DataFlowRequirement:
  source_capability:   dimension               # e.g., sensing.rgb
  sink_capability:     dimension               # e.g., compute.gpu
  bandwidth_kbps:      float                   # minimum required bandwidth
  max_latency_ms:      float or None           # maximum acceptable one-way latency
```

For a coalition to be **communication-feasible**, every data flow requirement must have a viable communication path between the member providing the source capability and the member providing the sink capability.

```
DataFlowLink:
  source_node:         NodeId                  # provider of source capability
  sink_node:           NodeId                  # provider of sink capability
  required_bw_kbps:    float                   # from DataFlowRequirement
  available_bw_kbps:   float                   # estimated from link quality
  latency_ms:          float                   # estimated one-way latency
  feasible:            bool                    # available >= required
```

### 2.6 Coalition cost

```
CoalitionCost:
  member_execution_cost:  float    # Σ execution cost of each member for their role
  data_transfer_cost:     float    # Σ bandwidth × time for all data flow links
  coordination_overhead:  float    # fixed per-member overhead for sync messages
  fragility_penalty:      float    # penalty proportional to coalition size (more members = more failure risk)
```

Total coalition cost:

```
cost(Γ, τ_j) = member_execution_cost
             + data_transfer_cost
             + coordination_overhead × |Γ|
             + fragility_penalty × (|Γ| - 1)
```

### 2.7 CoalitionStatus

| Status | Meaning |
|--------|---------|
| FORMING | Coalition proposed, awaiting member acknowledgments |
| ACTIVE | All members acknowledged, task executing |
| DEGRADED | A member lost or degraded, coalition operating at reduced quality |
| DISSOLVED | Coalition disbanded (task completed, failed, or abandoned) |

---

## 3. ASSUMPTIONS

**A1. Solo matching has been attempted.**  Coalition formation is triggered only after Algorithm 003 confirms no solo node is eligible for the task at its current tier.

**A2. Link quality is approximately known.**  Each node knows the approximate quality, bandwidth, and latency of its direct communication links to neighbors.  This information comes from recent heartbeat exchanges and message timing.  Multi-hop link quality is estimated from pairwise link information via gossip.

**A3. Capability reports are available.**  The coalition initiator has received recent `CapabilityReport` messages (from 001) from at least some neighbors.  Staleness applies (from 003).

**A4. Coalition size is bounded.**  v0.1 limits coalitions to a maximum of K_max = 4 members.  The combinatorial search space grows as C(|S|, k) for coalition size k.  With K_max = 4 and swarm size ≤ 20, this is computationally feasible for greedy search.

> **This is a PROVISIONAL v0.1 CHOICE.** The limit K_max = 4 is driven by computational tractability and the practical observation that coalitions larger than 4 have high coordination overhead and fragility.  If real-world scenarios require larger coalitions, this bound must be relaxed with a corresponding investment in search heuristics.

**A5. Greedy construction does not guarantee optimal composition.**  The greedy incremental algorithm (§8) may miss a better coalition that a different seed or ordering would find.  v0.1 accepts this limitation.

**A6. Coalition formation is initiated locally.**  The node that detects an unsatisfied task initiates coalition formation.  This is NOT a permanent central role — any node detecting a need can initiate.

**A7. Tasks specify data flow requirements.**  Coalition feasibility checking requires the task's `data_flow` specification (from 002).  If a task has no data flow requirements, communication feasibility is trivially satisfied.

**A8. Members must consent.**  A node cannot be unilaterally added to a coalition.  In v0.1, consent is simplified: a node accepts coalition membership if it is not at energy critical level and has uncommitted capacity for the role.

---

## 4. INPUTS

### At the coalition initiator

| Input | Source | Description |
|-------|--------|-------------|
| τ_j | Task discovery / 006 degradation | The task requiring coalition execution |
| R_j | Algorithm 002 | Task requirements (required, preferred, data_flow) |
| candidates | Local knowledge | Set of known nodes (may be subset of true swarm) |
| {C_k} for k ∈ candidates | Received CapabilityReports | Last-known capability states (with staleness) |
| {q_{ik}, bw_{ik}, lat_{ik}} | Local measurement + gossip | Link quality metrics to/between candidates |
| match_results | Algorithm 003 | Per-candidate eligibility and partial match details |

### At each candidate node (upon receiving coalition proposal)

| Input | Source | Description |
|-------|--------|-------------|
| CoalitionProposal | Received message | Proposed coalition: task, members, role_assignment |
| C_i | Local measurement | Own current capability state |
| current_commitments | Local ledger | Tasks already assigned to this node |
| ε_i | Local measurement | Own energy level |

---

## 5. LOCALLY AVAILABLE INFORMATION

### KNOWN LOCALLY
- Own capability state C_i (fresh, no staleness)
- Own energy level ε_i
- Own current task commitments
- Direct link qualities to immediate neighbors: {q_{ij}, bw_{ij}, lat_{ij}} for neighbors j

### RECEIVED VIA MESSAGES
- Other nodes' CapabilityReports with (source_id, lamport_clock, wall_time, capability_state) — subject to staleness
- Gossiped link quality between other pairs of nodes (second-hand; less reliable than direct measurement)
- Task announcements and their requirements

### INFERRED
- Which dimensions each candidate can provide (from their CapabilityReports)
- Potential coalition compositions (computed by this algorithm)
- Communication feasibility between candidate pairs (estimated from known link metrics)
- Coalition cost estimates

### UNKNOWN
- Capabilities of unreachable nodes (may exist beyond communication horizon)
- Actual current link quality between two remote nodes (only estimated from gossip or historical data)
- Whether a candidate node is willing and available to join (until consent message received)
- How a candidate's capability state has changed since its last report
- Future link quality changes (topology is dynamic)

---

## 6. OUTPUT

### Primary output: Coalition or None

```
CoalitionResult:
  success:           bool
  coalition:         Coalition or None          # if success
  rejection_reason:  string or None             # if failure
  candidates_tried:  int                        # number of compositions evaluated
  best_partial:      {dimensions_covered, dimensions_missing}  # if failed, what was closest
```

### Secondary outputs

- **Role assignment:** which member provides which capability dimensions
- **Data flow plan:** which communication links carry which data, at what bandwidth
- **Cost estimate:** total coalition cost for comparison against degraded-solo alternatives
- **Comparison recommendation:** if a degraded solo execution at a lower tier would be cheaper, flag this for 006 (Graceful Degradation) to decide

---

## 7. DECISION RULE

### 7.1 Coalition formation trigger

Coalition formation is invoked when:
1. A task τ_j exists in state ANNOUNCED or BIDDING
2. Algorithm 003 returns no eligible solo node (all nodes fail at least one required dimension)
3. At least 2 candidate nodes are known (cannot form a multi-node coalition with fewer than 2)

### 7.2 Capability composition

For a candidate coalition Γ = {n_a, n_b, ...}, compute the composed capability:

```
For each required dimension d in R_j^req:
  type_d = dimension_type(d)
  IF type_d == BOOLEAN:
    c_{Γ,d} = 1  if any member has c_{k,d} == 1 (OR)
  ELIF type_d == CONTINUOUS:
    c_{Γ,d} = max(c_{k,d} for k in Γ)           (MAX)
    provider_d = argmax(c_{k,d} for k in Γ)
  ELIF type_d == CAPACITY:
    c_{Γ,d} = sum(c_{k,d} for k in Γ) - overhead_per_member × |Γ|  (SUM minus overhead)
    provider_d = node with largest c_{k,d}        (primary provider)
  ELIF type_d == CATEGORICAL:
    c_{Γ,d} = union(c_{k,d} for k in Γ)          (SET UNION)
    provider_d = first member whose c_{k,d} matches requirement
```

The `overhead_per_member` for CAPACITY dimensions accounts for coordination overhead consuming some of each member's capacity.  v0.1 default: 5% of individual capacity per additional member.

### 7.3 Eligibility check on composed state

After composition, check eligibility identically to Algorithm 003:

```
coalition_eligible = check_eligibility(C_Γ, R_j^req)
```

If the composed state fails eligibility, this specific coalition cannot satisfy the task.

### 7.4 Communication feasibility check

For each DataFlowRequirement in τ_j.data_flow:
1. Identify `source_node` = provider_map[source_capability]
2. Identify `sink_node` = provider_map[sink_capability]
3. If source_node == sink_node → trivially feasible (local data path)
4. If source_node ≠ sink_node:
   a. Look up link metrics: bw_{source, sink}, lat_{source, sink}
   b. Check: bw_{source, sink} ≥ required_bandwidth_kbps
   c. Check: lat_{source, sink} ≤ max_latency_ms (if specified)
   d. If either fails → data flow infeasible

The coalition is communication-feasible only if ALL data flow requirements are satisfied.

### 7.5 Coalition cost computation

```
cost(Γ, τ_j) = Σ_k execution_cost(n_k, role_k)        # per-member execution cost for their role
             + Σ_flows (data_size_per_s × duration / bw)  # data transfer time cost
             + C_coord × |Γ|                              # coordination message overhead
             + C_frag × (|Γ| - 1)                         # fragility penalty
```

Where:
- `execution_cost(n_k, role_k)` is estimated energy and compute consumed by node k performing its assigned role
- `C_coord` is the per-member coordination overhead constant (v0.1 default: 0.1 normalized units)
- `C_frag` is the fragility penalty per additional member (v0.1 default: 0.15 normalized units)

### 7.6 Greedy selection criterion

When choosing the next node to add to a coalition, rank candidates by:

```
score(n_k) = gaps_filled(n_k) / (1 + comm_cost_to_existing_members(n_k))
```

Where:
- `gaps_filled(n_k)` = number of currently-unsatisfied required dimensions that n_k would satisfy
- `comm_cost_to_existing_members(n_k)` = average inverse bandwidth to existing coalition members (higher cost for poorly connected candidates)

This balances gap coverage against communication cost.

---

## 8. PLAIN-ENGLISH ALGORITHM

### Coalition formation: greedy incremental construction

1. **Initialize.**  Take the task τ_j and its required dimensions R_j^req.  Compute the "gap set" — the set of required dimensions that no single node satisfies.

2. **Rank candidates by coverage.**  For each candidate node, compute how many gap dimensions it can satisfy (at or above the required threshold).

3. **Seed the coalition.**  Select the candidate that covers the most gap dimensions as the "partial match champion."  This node becomes the coalition seed.

4. **Update the gap set.**  Remove dimensions now covered by the seed.

5. **Iterative expansion.**  While the gap set is non-empty and coalition size < K_max:
   a. From remaining candidates, select the node that:
      - Fills the most remaining gaps, AND
      - Has a communication link to at least one existing coalition member with non-zero bandwidth
   b. Add this node to the coalition.
   c. Update the gap set.
   d. If no candidate fills any gap OR no candidate is communication-reachable → STOP (formation fails).

6. **Eligibility verification.**  Apply Algorithm 003's eligibility check to the composed capability state.

7. **Communication feasibility.**  Check all data flow requirements against actual link metrics between providers.  If any data flow is infeasible → try rearranging provider assignments (a different member might provide the same dimension).  If still infeasible → formation fails.

8. **Cost estimation.**  Compute coalition cost (§7.5).

9. **Comparison against degraded solo.**  If the task has a lower degradation tier (from 002) and any solo node could execute at that tier, compute the degraded-solo cost.  If degraded-solo cost < coalition cost and degraded quality ≥ minimum_acceptable_quality → flag the comparison for Algorithm 006 to decide.

10. **Proposal.**  Send `CoalitionProposal` to each member.  Wait for consent within a bounded window.  If any member rejects or times out → try replacing that member.  If no replacement → formation fails.

11. **Activation.**  If all members consent → coalition status = ACTIVE.  Record in local ledger.  Begin execution.

---

## 9. PSEUDOCODE

```python
def form_coalition(task, candidates, link_metrics, K_max=4):
    """
    Attempt to form a coalition for task from candidates.
    Returns CoalitionResult.
    
    All inputs are locally known or received via messages.
    No global state is accessed.
    """
    required = task.R_j_req                  # required dimensions with thresholds
    gap_set = set(required.keys())           # dimensions not yet covered
    coalition_members = []
    provider_map = {}
    
    # --- Phase 1: Greedy incremental construction ---
    
    available = list(candidates)
    
    while gap_set and len(coalition_members) < K_max and available:
        
        # Score each candidate by gaps filled and comm cost
        best_score = -1
        best_candidate = None
        
        for n_k in available:
            gaps_filled = 0
            for d in gap_set:
                if dimension_meets_threshold(n_k.C[d], required[d]):
                    gaps_filled += 1
            
            if gaps_filled == 0:
                continue
            
            # Communication reachability to existing coalition
            if coalition_members:
                comm_cost = avg_inverse_bandwidth(n_k, coalition_members, link_metrics)
                if comm_cost == INFINITY:  # no link to any member
                    continue
            else:
                comm_cost = 0  # seed node, no existing members
            
            score = gaps_filled / (1.0 + comm_cost)
            
            if score > best_score:
                best_score = score
                best_candidate = n_k
        
        if best_candidate is None:
            break  # no candidate can fill any remaining gap
        
        # Add to coalition
        coalition_members.append(best_candidate)
        available.remove(best_candidate)
        
        # Update gap set and provider map
        for d in list(gap_set):
            if dimension_meets_threshold(best_candidate.C[d], required[d]):
                gap_set.discard(d)
                provider_map[d] = best_candidate.id
    
    # --- Phase 2: Verification ---
    
    if gap_set:
        return CoalitionResult(
            success=False,
            rejection_reason=f"Cannot cover dimensions: {gap_set}",
            candidates_tried=len(candidates) - len(available),
            best_partial={"covered": set(required.keys()) - gap_set, "missing": gap_set}
        )
    
    # Compose capability state
    composed = compose_capabilities(coalition_members, required)
    
    # Eligibility check on composed state
    if not check_eligibility(composed, required):
        return CoalitionResult(
            success=False,
            rejection_reason="Composed state fails eligibility (capacity overhead)",
        )
    
    # --- Phase 3: Communication feasibility ---
    
    data_flow_plan = []
    for flow in task.data_flow:
        source_node = provider_map.get(flow.source_capability)
        sink_node = provider_map.get(flow.sink_capability)
        
        if source_node is None or sink_node is None:
            return CoalitionResult(
                success=False,
                rejection_reason=f"No provider for {flow.source_capability} or {flow.sink_capability}",
            )
        
        if source_node == sink_node:
            # Local data path, trivially feasible
            data_flow_plan.append(DataFlowLink(
                source_node=source_node, sink_node=sink_node,
                required_bw=flow.bandwidth_kbps, available_bw=INFINITY,
                latency_ms=0, feasible=True
            ))
            continue
        
        # Check inter-node link
        bw_available = link_metrics.get_bandwidth(source_node, sink_node)
        latency = link_metrics.get_latency(source_node, sink_node)
        
        bw_ok = bw_available >= flow.bandwidth_kbps
        lat_ok = (flow.max_latency_ms is None) or (latency <= flow.max_latency_ms)
        
        if not (bw_ok and lat_ok):
            return CoalitionResult(
                success=False,
                rejection_reason=f"Link {source_node}->{sink_node}: "
                    f"need {flow.bandwidth_kbps}kbps/{flow.max_latency_ms}ms, "
                    f"have {bw_available}kbps/{latency}ms",
            )
        
        data_flow_plan.append(DataFlowLink(
            source_node=source_node, sink_node=sink_node,
            required_bw=flow.bandwidth_kbps, available_bw=bw_available,
            latency_ms=latency, feasible=True
        ))
    
    # --- Phase 4: Cost estimation ---
    
    total_cost = estimate_coalition_cost(coalition_members, task, data_flow_plan)
    
    # --- Phase 5: Build coalition structure ---
    
    coalition = Coalition(
        coalition_id=generate_id(),
        task_id=task.task_id,
        members=[m.id for m in coalition_members],
        initiator=self.node_id,
        role_assignment=provider_map,
        composed_state=composed,
        data_flow_plan=data_flow_plan,
        estimated_cost=total_cost,
        formation_time=local_wall_time(),
        status=FORMING
    )
    
    return CoalitionResult(success=True, coalition=coalition)


def compose_capabilities(members, required_dims):
    """
    Apply type-dependent composition rules to produce ComposedCapabilityState.
    """
    composed = {}
    providers = {}
    
    for d, threshold in required_dims.items():
        semantic = dimension_composition_semantic(d)
        
        if semantic == MAX:
            best_member = max(members, key=lambda m: m.C.get(d, 0.0))
            composed[d] = best_member.C.get(d, 0.0)
            providers[d] = best_member.id
            
        elif semantic == SUM_DIVISIBLE:
            raw_sum = sum(m.C.get(d, 0.0) for m in members)
            overhead = CAPACITY_OVERHEAD_FRACTION * len(members)
            composed[d] = raw_sum * (1.0 - overhead)
            providers[d] = max(members, key=lambda m: m.C.get(d, 0.0)).id
            
        elif semantic == NON_COMPOSABLE:
            # Check if any single member meets the threshold on their own
            valid_members = [m for m in members if m.C.get(d, 0.0) >= threshold]
            if not valid_members:
                composed[d] = 0.0
                providers[d] = None
            else:
                best_member = max(valid_members, key=lambda m: m.C.get(d, 0.0))
                composed[d] = best_member.C.get(d, 0.0)
                providers[d] = best_member.id
        
        elif semantic == UNION:
            combined_set = set()
            for m in members:
                val = m.C.get(d)
                if val:
                    combined_set.add(val) if isinstance(val, str) else combined_set.update(val)
            composed[d] = combined_set
            # Provider is first member whose value matches requirement
            providers[d] = first(m.id for m in members if matches_categorical(m.C.get(d), threshold))
    
    return ComposedCapabilityState(
        members=[m.id for m in members],
        composed_values=composed,
        provider_map=providers,
    )


def estimate_coalition_cost(members, task, data_flow_plan):
    """Estimate total cost of coalition execution."""
    
    # Per-member execution cost (energy, compute time)
    exec_cost = sum(
        estimate_member_execution_cost(m, task)
        for m in members
    )
    
    # Data transfer cost
    transfer_cost = sum(
        flow.required_bw * task.estimated_duration_s / flow.available_bw
        for flow in data_flow_plan
        if flow.source_node != flow.sink_node
    )
    
    # Coordination overhead (per member)
    coord_cost = C_COORD * len(members)
    
    # Fragility penalty (per additional member beyond 1)
    frag_cost = C_FRAG * (len(members) - 1)
    
    return exec_cost + transfer_cost + coord_cost + frag_cost
```

---

## 10. WORKED EXAMPLE

### Scenario: mapping_zone_b coalition after node loss

**Task:** `mapping_zone_b` (from 002)
```
Required:   sensing.rgb ≥ 0.7, localization ≥ 0.8, compute.gpu_available ≥ 0.5
Preferred:  sensing.lidar ≥ 0.8
Priority:   π = 0.91 (CRITICAL)
Data flow:  [(sensing.rgb → compute.gpu, 5000 kbps, max_latency=200ms),
             (compute.gpu → output.map, 100 kbps, None)]
```

**Locally known nodes (after Node A lost):**

| Node | rgb | localization | gpu_available | vram_mb | thermal | runtime |
|------|-----|-------------|---------------|---------|---------|---------|
| Drone B | 0.9 | 0.9 | 0.2 | 512 | false | cpu_only |
| Rover C | 0.1 | 0.3 | 0.8 | 4096 | false | cuda |
| Relay D | 0.0 | 0.1 | 0.3 | 1024 | false | cuda |

**Solo eligibility (from 003):** All fail.  B fails gpu.  C fails rgb, localization.  D fails everything.

**Step 1: Gap set** = {sensing.rgb ≥ 0.7, localization ≥ 0.8, compute.gpu_available ≥ 0.5}

**Step 2: Rank candidates by gaps filled**

| Candidate | Gaps filled | Details |
|-----------|------------|---------|
| Drone B | 2 | rgb=0.9 ✓, localization=0.9 ✓, gpu=0.2 ✗ |
| Rover C | 1 | rgb=0.1 ✗, localization=0.3 ✗, gpu=0.8 ✓ |
| Relay D | 0 | rgb=0.0 ✗, localization=0.1 ✗, gpu=0.3 ✗ |

**Step 3: Seed** = Drone B (fills 2 gaps, partial match champion).

**Step 4: Gap set** = {compute.gpu_available ≥ 0.5} (rgb and localization covered by B).

**Step 5: Iterative expansion**

Remaining candidates: Rover C, Relay D.

| Candidate | Gaps filled | Comm to B (bw_kbps) | Score |
|-----------|------------|---------------------|-------|
| Rover C | 1 (gpu=0.8 ✓) | 8000 | 1.0 / (1 + 1/8000) ≈ 1.0 |
| Relay D | 0 | — | — (no gaps filled) |

Select Rover C.  Coalition = {B, C}.

**Step 6: Gap set** = {} (all gaps covered).

**Step 7: Compose capabilities**

| Dimension | Type | B value | C value | Rule | Composed |
|-----------|------|---------|---------|------|----------|
| sensing.rgb | CONTINUOUS | 0.9 | 0.1 | MAX | 0.9 (provider: B) |
| localization | CONTINUOUS | 0.9 | 0.3 | MAX | 0.9 (provider: B) |
| compute.gpu | CONTINUOUS | 0.2 | 0.8 | MAX | 0.8 (provider: C) |

Eligibility check: rgb=0.9 ≥ 0.7 ✓, loc=0.9 ≥ 0.8 ✓, gpu=0.8 ≥ 0.5 ✓.  **ELIGIBLE.**

**Step 8: Communication feasibility**

Data flow 1: sensing.rgb → compute.gpu = B → C (rgb provided by B, gpu provided by C)
- Required: 5000 kbps, max latency 200ms
- Link B↔C: bw = 8000 kbps ✓, latency = 45ms ✓
- **FEASIBLE**

Data flow 2: compute.gpu → output.map = C → (output)
- Provider of output.map is the task requester or local storage.
- If output stays on C or requires 100 kbps → trivially feasible.
- **FEASIBLE**

**Step 9: Cost estimation**

```
Member execution:   B(sensing) = 0.3,  C(compute) = 0.5     → 0.8
Data transfer:      5000kbps × est_60s / 8000kbps = 37.5    → 0.38 (normalized)
Coordination:       0.1 × 2 members                         → 0.2
Fragility:          0.15 × (2-1)                             → 0.15
                                                    Total:     1.53
```

**Step 10: Result**

```
Coalition {B, C} formed for mapping_zone_b
  Role: B provides sensing.rgb, localization
  Role: C provides compute.gpu
  Data flow: B→C at 5000kbps (link capacity 8000kbps, headroom 37.5%)
  Estimated cost: 1.53
  Status: FORMING (awaiting member consent)
```

---

## 11. EDGE CASES

### E1: Maximum-size coalition required

If a task requires 4 distinct capabilities and each candidate covers exactly one, the coalition must include all 4.  With K_max = 4, this is at the boundary.  If K_max = 3, the task would fail despite being theoretically satisfiable.

**Handling:** The bound K_max should be set conservatively based on the maximum task complexity in the mission specification.  v0.1 uses K_max = 4 as default but accepts this as a parameter.

### E2: Coalition member fails during execution

A member of an ACTIVE coalition crashes or degrades below its role's requirements.

**Handling:** This is delegated to Algorithm 006 (Graceful Degradation).  The coalition transitions to DEGRADED status.  006 may attempt to find a replacement member (re-running coalition formation with the remaining members as a partial seed) or descend to a lower degradation tier.

### E3: Coalition candidate is also being recruited by another coalition

Node C receives two CoalitionProposals simultaneously for different tasks.

**Handling:** v0.1 applies first-come-first-served: the first proposal received is evaluated.  If the node accepts, subsequent proposals are rejected with reason "committed."  This is a simplification.

> **PROVISIONAL v0.1 CHOICE.**  A more sophisticated approach would evaluate which coalition to join based on task priority (π_j).  The node would accept the proposal for the higher-priority task.  This requires holding proposals for a brief decision window, adding latency.  Deferred to future versions.

### E4: Communication-feasible coalition with no bandwidth headroom

The required bandwidth exactly matches available bandwidth (e.g., need 5000 kbps, have 5000 kbps).

**Handling:** This is flagged as MARGINAL in the feasibility check.  The coalition is accepted but with a warning annotation in the Coalition structure.  Any bandwidth degradation during execution will make the data flow infeasible.  006 should monitor link quality and prepare for degradation.

### E5: Coalition where one member provides ALL required dimensions

If one node covers all gaps, the "coalition" is a single node — which should have been caught by solo matching (003).  This can only happen if the node became eligible between the solo check and coalition formation (e.g., it freed resources).

**Handling:** Accept the singleton coalition and convert it to a solo assignment.

### E6: No candidates known at all

The initiator has no CapabilityReports from any other node (partitioned, just joined, or all neighbors lost).

**Handling:** Coalition formation returns failure immediately.  The task is escalated to 006 for degradation tier descent or abandonment.

---

## 12. FAILURE MODES

### F1: Stale capability reports lead to infeasible coalition

The initiator forms a coalition based on Node C's report (gpu=0.8) but C's GPU has since crashed (true gpu=0.0).  The coalition is proposed, C accepts (if it doesn't re-check), and execution fails immediately.

**Mitigation:** Consent protocol requires each member to re-evaluate its own eligibility for its assigned role BEFORE accepting.  If the member no longer meets the role's requirements, it rejects the proposal.

### F2: Link quality changes between formation and execution

The link between B and C was 8000 kbps during formation but dropped to 2000 kbps by execution time.  Data flow requirement (5000 kbps) is no longer met.

**Mitigation:** Coalition execution monitors link quality in real-time.  If quality drops below the data flow requirement, the coalition transitions to DEGRADED and 006 is invoked.  This is a runtime concern, not a formation-time failure.

### F3: Greedy construction misses better coalition

Greedy selects B as seed (2 gaps) then adds C.  But a coalition {C, D} with D providing camera through a higher-quality link might have been cheaper overall.

**Mitigation:** v0.1 accepts this limitation.  For v0.2, a bounded exploration phase could evaluate the top-K seeds (e.g., top 2-3 by gap coverage) and compare the resulting coalitions.

### F4: Consent timeout

A proposed member does not respond within the consent window (lost message, busy, partitioned).

**Mitigation:** The initiator treats timeout as rejection and attempts to find a replacement from remaining candidates.  If no replacement exists, coalition formation fails.

### F5: All nodes want to initiate coalition for the same task

Multiple nodes independently detect that task τ_j needs a coalition and each starts forming one.  This could lead to conflicting proposals or the same node being recruited into two coalitions for the same task.

**Mitigation:** v0.1 relies on the task lifecycle state machine (from 002).  Once a coalition is formed and the task transitions to ASSIGNED, subsequent coalition proposals for the same task are rejected.  In the race condition where two coalitions form simultaneously, the first to successfully transition the task wins.  The other dissolves.

---

## 13. INVARIANTS

**I1. No coalition member accesses global simulation truth.**  All capability and link information used in formation comes from local state or received messages.

**I2. Coalition membership requires consent.**  No node is added to a coalition without its acknowledgment.

**I3. Physical capabilities are not transferred.**  A coalition does NOT move a camera from B to C.  It routes camera data from B to C over a communication link.  The camera remains physically on B.

**I4. Every coalition has an explicit data flow plan.**  No coalition is formed without verifying that the required data movement between members is communication-feasible.

**I5. Coalition size ≤ K_max.**  The algorithm never produces coalitions exceeding the configured maximum.

**I6. Coalition feasibility implies both capability sufficiency AND communication feasibility.**  A coalition that has sufficient composed capabilities but infeasible data flows is NOT formed.

**I7. Greedy construction is deterministic.**  Given the same inputs (candidates, capabilities, link metrics), the algorithm produces the same coalition.  This is important for consistency across nodes that may independently evaluate coalition viability.

**I8. Coalition cost is always computed.**  No coalition is proposed without an explicit cost estimate that can be compared against alternatives (other coalitions, degraded solo execution).

---

## 14. OPEN QUESTIONS

### Q1: Greedy vs. optimal coalition search

**Question:** Is greedy incremental construction adequate, or does HESK need optimal (or near-optimal) search?

**Options:**
| Approach | Time complexity | Quality guarantee | Practical for K_max=4? |
|----------|----------------|-------------------|----------------------|
| Greedy incremental | O(|S| × K_max) | No guarantee | Yes |
| Exhaustive search | O(C(|S|, K_max)) | Optimal | Feasible for |S| ≤ 15, K_max ≤ 4 |
| Top-K seeds + greedy | O(K × |S| × K_max) | Better than greedy, not optimal | Yes |

**Provisional v0.1 choice:** Greedy incremental.  Justification: with K_max = 4 and swarm size ≤ 20, even exhaustive search (C(20,4) = 4845) is computationally feasible.  However, the greedy approach is simpler to implement, debug, and trace.  If experiments show significant quality loss from greedy, upgrade to exhaustive search within the bounded K_max.

### Q2: Unified bidding — should solo bids and coalition proposals compete in the same round?

**Question:** Should Algorithm 004 (solo allocation) and Algorithm 005 (coalition formation) run independently, or should a task allocation round collect both solo bids and coalition proposals and compare them in a unified evaluation?

**Options:**
- **Sequential (v0.1):** Try solo first (004).  If no eligible solo node, try coalition (005).
- **Unified:** Collect both solo bids and coalition proposals in the same bid window.  Compare solo system cost against coalition cost.

**Provisional v0.1 choice:** Sequential.  Justification: simpler protocol, fewer message types, clearer separation of concerns.  Coalition formation is strictly a fallback.

**Tradeoff:** A coalition might actually be BETTER than the best solo node even when a solo node is eligible (e.g., the coalition distributes load better).  Sequential misses this.

### Q3: How to handle coalition member failure during execution?

**Question:** When a member of an active coalition fails or degrades, should the coalition attempt self-repair (replace the member) or immediately escalate to Algorithm 006?

**Options:**
- **Immediate escalation:** Coalition reports failure to 006, which decides between re-formation, tier descent, or task abandonment.
- **Self-repair:** Coalition initiator attempts to find a replacement member before escalating.
- **Hybrid:** Allow one self-repair attempt; if it fails, escalate.

**Provisional v0.1 choice:** Immediate escalation to 006.  Justification: keeps coalition formation stateless (it forms, then hands off).  Self-repair adds complexity and may make poor decisions without 006's priority-ordering logic.

### Q4: Should coalitions have internal leadership?

**Question:** Should one member of a coalition be designated as the "coalition coordinator" responsible for monitoring member health and data flow quality?

**Options:**
- **No coordinator:** Each member independently monitors its own role and reports failures.
- **Initiator as coordinator:** The node that formed the coalition monitors overall health.
- **Rotating coordinator:** Coordinator role passes between members.

**Provisional v0.1 choice:** Initiator as coordinator.  Justification: the initiator already has the complete data flow plan and role assignment.  It monitors heartbeats from members and detects failures.  This is NOT a permanent central coordinator (it's scoped to one coalition for one task), consistent with HESK Invariant 3.

### Q5: When is degraded solo execution preferable to a coalition?

**Question:** If task τ_j at Tier 1 (quality 0.70) can be executed solo by Node B, and a coalition {B, C} can execute at Tier 0 (quality 1.0) but at higher cost and fragility, which should HESK choose?

**Tradeoff:** Higher quality vs. lower risk and cost.  The answer depends on π_j (mission priority), the cost ratio, and how critical quality 1.0 is vs. quality 0.70.

**v0.1 approach:** Coalition formation computes the coalition cost and flags the comparison to Algorithm 006.  006 makes the final decision based on priority-weighted utility (π_j × quality).

---

## 15. BASELINE FOR COMPARISON

### Baseline A: No coalitions (solo-only execution)

If no single node can satisfy a task → task FAILS.  No multi-node execution attempted.

**What this loses:**
- In the worked example, mapping_zone_b would fail entirely despite B and C jointly having all required capabilities.
- Every task requiring capabilities split across nodes is abandoned.
- Mission utility drops to zero for any task that exceeds individual node capabilities.

### Baseline B: Random grouping

Form coalitions by randomly selecting K nodes from the candidate set.

**What this gets wrong:**
- Ignores whether the randomly selected nodes actually cover the required dimensions.
- Ignores communication feasibility — may group nodes with no communication link.
- Ignores cost — may select expensive nodes when cheaper alternatives exist.

### Baseline C: Capability-aware but communication-unaware

Form coalitions by greedily selecting nodes that cover the most gaps, but without checking communication feasibility.

**What this gets wrong (from HESK Scope §10 and Construction Guide Problem 14):**
- May form a coalition where Node A has the camera and Node C has the compute, but A↔C link bandwidth is 100 kbps while the data flow requires 5000 kbps.
- The coalition looks feasible on paper but fails operationally.
- This is the specific failure mode that HESK's communication-feasibility check addresses.

### Comparison metrics

| Metric | Baseline A | Baseline B | Baseline C | HESK 005 |
|--------|-----------|-----------|-----------|----------|
| Tasks satisfied | Solo-satisfiable only | Random chance | Higher than B | Capability + comm aware |
| Communication failures | N/A | High | HIGH | Low (checked) |
| Wasted coalitions | 0 | High | Medium-High | Low |
| Coalition cost tracked | N/A | No | No | Yes |
| Fragility considered | N/A | No | No | Yes |
