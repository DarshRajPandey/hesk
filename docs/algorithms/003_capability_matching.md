# Capability Matching

> **Algorithm 003** — First consumer of [001 Capability Model](./001_capability_model.md) and [002 Task Model](./002_task_model.md).
> Feeds into [004 Scarcity Allocation](./004_scarcity_allocation.md) and [005 Coalition Formation](./005_coalition_formation.md).

---

## 1. PROBLEM

Given a node's capability state C_i and a task's requirement state R_j, determine:

1. **Is the node eligible?** — Does C_i satisfy every required dimension in R_j?
2. **How good is the match?** — Among eligible nodes, how well does C_i satisfy the preferred dimensions in R_j?

These are two separate questions answered by two separate operations.

### Why this matters

Capability matching is the bridge between WHAT a node CAN DO (001) and WHAT a task NEEDS (002).
Every downstream HESK decision — allocation bids (004), coalition ranking (005), degradation planning (006) — depends on matching results.
A matching engine that conflates eligibility with preference, or that ignores capability types, will silently produce allocation decisions that cannot be explained or trusted.

### The core tension

A naive approach treats all capability dimensions as numbers and computes a single similarity score.
This is convenient but wrong.

- A node without a camera cannot perform visual mapping regardless of its compute surplus.
- A node with an incompatible GPU runtime scores 0.0 for that dimension, not 0.5.
- A node whose capability report is 90 seconds old may have changed state entirely.

Capability matching must be **type-aware**, **staleness-aware**, and **two-phase**.

---

## 2. DEFINITIONS

### 2.1 Notation

| Symbol | Meaning |
|---|---|
| C_i | Capability state of node i, as defined in 001 |
| R_j | Requirement state of task j, as defined in 002 |
| R_j^req | Set of required dimensions in R_j (hard constraints) |
| R_j^pref | Set of preferred dimensions in R_j (soft preferences) |
| d | A single capability dimension (e.g., `sensing.rgb`, `compute.gpu_available`) |
| C_i[d] | Node i's value for dimension d |
| R_j[d] | Task j's requirement for dimension d |
| τ_d | Threshold value for dimension d in R_j |
| age_s | Seconds elapsed since capability report was generated |
| t_half | Staleness half-life parameter (seconds) |
| σ(age_s) | Confidence decay function: σ(age_s) = exp(−age_s / t_half) |

### 2.2 Capability dimension types

From Construction Guide Problem 10 and HESK Scope §3, each dimension has a type:

| Type | Description | Example dimensions | Comparison semantics |
|---|---|---|---|
| BOOLEAN | Binary has/does-not-have | `sensing.thermal`, `payload.gripper` | Has = true vs required = true |
| CONTINUOUS | Normalized scalar [0, 1] | `sensing.rgb`, `energy`, `link_quality` | value ≥ threshold |
| CAPACITY | Absolute measurable quantity | `compute.gpu_tflops`, `payload_kg` | value ≥ threshold (absolute units) |
| CATEGORICAL | Membership in a compatibility set | `compute.runtime`, `radio.protocol` | value ∈ required_set |

### 2.3 Key terms

**Eligibility** — A binary determination: does the node meet ALL required dimensions? Eligibility is a gate, not a score. A node is either eligible or not.

**Match quality** — A scalar ∈ [0, 1] measuring how well an eligible node satisfies the preferred dimensions. Match quality is a ranking signal, not a gate.

**Surplus** — For CONTINUOUS and CAPACITY dimensions, the amount by which a node's value exceeds the threshold: surplus_d = C_i[d] − τ_d. Surplus is always ≥ 0 for met dimensions.

**Staleness** — The age of a capability report in seconds. Staleness reduces confidence in the report's accuracy. A node evaluating its own capabilities has staleness = 0.

**Confidence** — A scalar ∈ (0, 1] representing trust in a capability report. Computed as σ(age_s) for remote reports, and 1.0 for self-evaluation.

**MatchResult** — The structured output of a full match operation, containing eligibility, quality, confidence, and per-dimension detail.

---

## 3. ASSUMPTIONS

### 3.1 Structural assumptions

A1. **001 and 002 are defined.** Node capability states (C_i) follow the schema in 001. Task requirements (R_j) follow the schema in 002, with explicit required/preferred partitioning.

A2. **Dimension names are shared.** Nodes and tasks use a common dimension namespace. If task R_j requires dimension `sensing.lidar`, then node C_i either has an entry for `sensing.lidar` or it does not. There is no fuzzy name matching.

A3. **Type tags are available.** Each dimension carries its type (BOOLEAN, CONTINUOUS, CAPACITY, CATEGORICAL). The matching engine does not guess types from values.

A4. **Required vs preferred is explicit.** Every dimension in R_j is tagged as either required or preferred. There is no ambiguity.

### 3.2 Operational assumptions

A5. **Self-evaluation is instantaneous.** When a node evaluates its own capability state against a task, age_s = 0 and confidence = 1.0.

A6. **Remote reports have provenance.** When a node evaluates a received capability report from another node, the report carries a generation timestamp. The evaluating node computes age_s from its own local clock.

A7. **Clock drift is bounded.** For v0.1, clock drift between nodes is assumed small enough that age_s calculations are meaningful. This assumption will be revisited in 007/008.

A8. **Missing dimensions are negative.** If R_j requires dimension d but C_i has no entry for d, the node is treated as NOT having that capability. This is a conservative assumption; it is safer to reject a node than to assume it can do something it hasn't reported.

### 3.3 Scope boundaries

A9. **003 does not allocate.** This algorithm determines WHETHER a node CAN do a task and HOW WELL. It does not decide WHETHER IT SHOULD. Allocation is 004's responsibility.

A10. **003 does not compose.** Coalition capability composition (can A+B together satisfy R_j?) is 005's responsibility. 003 evaluates single-node match only.

A11. **003 does not consider cost.** Energy cost, communication cost, and scarcity cost are outside scope. 003 produces a MatchResult; 004 combines it with cost signals to produce an allocation bid.

---

## 4. INPUTS

### 4.1 Primary inputs

```
FUNCTION compute_full_match(C_i, R_j, age_s) → MatchResult
```

| Input | Type | Source | Description |
|---|---|---|---|
| C_i | CapabilityState | 001 schema | Node i's capability state — a dictionary of dimension → value entries, each with a type tag |
| R_j | TaskRequirement | 002 schema | Task j's requirement state — dimensions partitioned into R_j^req and R_j^pref, each with type tag and threshold/value |
| age_s | float ≥ 0 | Local computation | Seconds since C_i was generated. 0 for self-evaluation. Positive for received remote reports |

### 4.2 Configuration parameters

| Parameter | Type | Default | Description |
|---|---|---|---|
| t_half | float > 0 | 30.0 | Staleness half-life in seconds. At age = t_half, confidence = e^(−1) ≈ 0.368 |
| confidence_floor | float ∈ (0, 1) | 0.05 | Minimum confidence. Reports below this are treated as UNKNOWN |
| surplus_cap | float > 0 | 1.0 | Maximum normalized surplus per dimension. Prevents a single over-provisioned dimension from dominating quality |

---

## 5. LOCALLY AVAILABLE INFORMATION

### KNOWN (own C_i — fresh, no staleness)

When node i evaluates itself against task R_j:

- C_i is the node's own, current capability state — read directly from local sensors, local resource monitors, and the 001 capability registry
- age_s = 0
- confidence = 1.0
- All dimension values reflect ground truth as observed by the node at decision time

This is **self-evaluation**. There is no information decay.

### RECEIVED (other nodes' reports with staleness)

When node i evaluates a remote node k against task R_j:

- C_k was received as a capability report message from node k (or relayed through another node)
- The report carries a generation timestamp t_gen
- Node i computes age_s = t_now − t_gen using its local clock
- Confidence decays: σ(age_s) = exp(−age_s / t_half)
- If σ(age_s) < confidence_floor, the report is treated as UNKNOWN — too stale to trust

This is **remote evaluation**. The matching result must be discounted by confidence.

### INFERRED

From KNOWN and RECEIVED information, node i can infer:

- Eligibility of self or remote node for task R_j
- Match quality of self or remote node
- Confidence-weighted match quality for remote nodes
- Which dimensions are met, which are not, and by how much

### UNKNOWN (true remote state)

Node i does NOT know:

- The actual current capability state of node k (only the last received report)
- Whether node k's capabilities have changed since the report was generated
- Whether the report was corrupted or delayed in transit
- Whether node k is still operational

**003 never accesses UNKNOWN information.** It operates on the last received report, discounted by staleness. If the report is too stale (below confidence_floor), the node is treated as if its capabilities are unknown, and eligibility cannot be determined.

---

## 6. OUTPUT

### 6.1 MatchResult structure

```
MatchResult {
    eligible:            bool        # Did C_i pass the eligibility gate?
    quality:             float       # Match quality ∈ [0, 1]. 0 if ineligible.
    confidence:          float       # Report confidence ∈ (0, 1]. 1.0 for self-eval.
    weighted_quality:    float       # quality × confidence. Final ranking signal.
    
    # Per-dimension detail (for explainability and 004/005 consumption)
    dimension_details:   dict[d → DimensionResult]
    
    # Summary flags
    unmet_required:      list[d]     # Required dims that were not met (empty if eligible)
    missing_dimensions:  list[d]     # Dims required by task but absent from C_i
}

DimensionResult {
    dimension:    string     # Dimension name
    dim_type:     DimType    # BOOLEAN | CONTINUOUS | CAPACITY | CATEGORICAL
    required:     bool       # Is this a required or preferred dimension?
    met:          bool       # Was the threshold satisfied?
    surplus:      float      # For CONTINUOUS/CAPACITY: value − threshold. Else 0.
    node_value:   any        # The node's actual value
    task_value:   any        # The task's threshold/requirement
    compatible:   bool       # For CATEGORICAL: is node_value in required_set?
}
```

### 6.2 Output consumers

| Consumer | What it reads | Purpose |
|---|---|---|
| 004 Scarcity Allocation | eligible, weighted_quality, dimension_details | Compute allocation bids; penalize scarce capability consumption |
| 005 Coalition Formation | eligible (per-dim), unmet_required, dimension_details | Find complementary nodes to cover unmet required dimensions |
| 006 Graceful Degradation | quality, missing_dimensions | Determine if degraded task execution is feasible |
| Decision trace / logging | All fields | Human-readable explanation of why a node was selected or rejected |

---

## 7. DECISION RULE

### 7.1 Phase 1: Eligibility gate

Eligibility is a hard gate. ALL required dimensions must be met. One failure → ineligible.

```
check_eligibility(C_i, R_j^req) → bool:
    FOR EACH dimension d IN R_j^req:
        IF d NOT IN C_i:
            RETURN false       # Missing dimension → does not have capability
        IF NOT compare(C_i[d], R_j[d]) .met:
            RETURN false       # Dimension present but below threshold
    RETURN true
```

**Rationale:** A task that requires `localization ≥ 0.7` cannot be performed by a node with `localization = 0.3`. This is not a preference — it is a hard physical constraint. Eligibility is not negotiable.

### 7.2 Per-type comparison functions

Each dimension type has its own comparison logic. These are NOT interchangeable.

#### 7.2.1 BOOLEAN comparison

```
compare_boolean(has: bool, required: bool) → {met: bool}:
    met = (has == true) OR (required == false)
    RETURN {met: met}
```

A BOOLEAN dimension is either present or absent. There is no surplus. If the task requires `thermal = true` and the node has `thermal = false`, the dimension is not met.

If the task does not require the dimension (`required = false`), any value satisfies.

#### 7.2.2 CONTINUOUS comparison

```
compare_continuous(value: float, threshold: float) → {met: bool, surplus: float}:
    met = (value ≥ threshold)
    surplus = max(value − threshold, 0.0)
    RETURN {met: met, surplus: surplus}
```

For normalized [0, 1] scalars. The node's value must meet or exceed the threshold. Surplus measures how much headroom exists.

Example: value = 0.91, threshold = 0.60 → met = true, surplus = 0.31.

#### 7.2.3 CAPACITY comparison

```
compare_capacity(value: float, threshold: float) → {met: bool, surplus: float}:
    met = (value ≥ threshold)
    surplus = max(value − threshold, 0.0)
    RETURN {met: met, surplus: surplus}
```

Structurally identical to CONTINUOUS, but operates on absolute units (TFLOPS, kg, Mbps) rather than normalized values. The distinction matters for quality aggregation — CAPACITY surplus must be normalized by threshold before aggregation (Section 7.4), while CONTINUOUS surplus is already in [0, 1] space.

Example: value = 12.0 TFLOPS, threshold = 8.0 TFLOPS → met = true, surplus = 4.0 TFLOPS.

#### 7.2.4 CATEGORICAL comparison

```
compare_categorical(value: string, required_set: set[string]) → {met: bool, compatible: bool}:
    compatible = (value IN required_set)
    met = compatible
    RETURN {met: met, compatible: compatible}
```

Categorical dimensions represent compatibility, not magnitude. A GPU runtime is either compatible or not — there is no "surplus" of compatibility.

Example: value = "tensorrt", required_set = {"tensorrt", "onnx"} → met = true, compatible = true.
Example: value = "coreml", required_set = {"tensorrt", "onnx"} → met = false, compatible = false.

### 7.3 Staleness decay

Capability reports from remote nodes decay with age. The confidence function models the increasing probability that the report no longer reflects reality.

```
compute_confidence(age_s: float) → float:
    IF age_s == 0:
        RETURN 1.0                                     # Self-evaluation
    raw = exp(−age_s / t_half)
    IF raw < confidence_floor:
        RETURN 0.0                                     # Report too stale; treat as UNKNOWN
    RETURN raw
```

**Decay behavior with default t_half = 30s:**

| age_s | confidence | Interpretation |
|---|---|---|
| 0 | 1.000 | Self-evaluation or just received |
| 5 | 0.846 | Recent report, high trust |
| 15 | 0.607 | Moderate age, still useful |
| 30 | 0.368 | One half-life elapsed, noticeably degraded |
| 45 | 0.223 | Significantly stale |
| 60 | 0.135 | Approaching uselessness |
| 90 | 0.050 | At confidence_floor — treated as UNKNOWN |

**Why exponential decay?**

1. Capability state changes are not uniformly distributed in time. Battery, compute load, and link quality can change rapidly. Exponential decay models increasing uncertainty.
2. The half-life parameter t_half is tunable per deployment. A high-dynamics environment (combat, disaster) would use a shorter half-life; a stable environment (infrastructure inspection) would use a longer one.
3. The confidence_floor prevents infinitely old reports from producing nonzero (but meaningless) confidence values.

### 7.4 Phase 2: Quality scoring

Quality scoring applies ONLY to eligible nodes. It measures how well the node satisfies preferred dimensions.

```
compute_match_quality(C_i, R_j^pref) → float:
    IF |R_j^pref| == 0:
        RETURN 1.0                      # No preferences → perfect quality by default
    
    total = 0.0
    FOR EACH dimension d IN R_j^pref:
        IF d NOT IN C_i:
            score_d = 0.0               # Missing preferred dim → zero contribution
        ELSE:
            result = compare(C_i[d], R_j[d])
            IF dim_type(d) == BOOLEAN OR dim_type(d) == CATEGORICAL:
                score_d = 1.0 IF result.met ELSE 0.0
            ELIF dim_type(d) == CONTINUOUS OR dim_type(d) == CAPACITY:
                satisfaction = 1.0 IF result.met ELSE 0.0
                IF R_j[d].threshold > 0:
                    headroom = min(result.surplus / R_j[d].threshold, surplus_cap)
                ELSE:
                    headroom = 0.0
                score_d = (w_sat × satisfaction) + (w_head × headroom)
        total += score_d
    
    quality = total / |R_j^pref|
    RETURN clamp(quality, 0.0, 1.0)
```

**v0.1 quality aggregation formula:**

For continuous and capacity dimensions, the score separates the binary satisfaction of the preference from the degree to which it is exceeded (headroom):

```
score_d = w_sat × I(met) + w_head × min(surplus_d / threshold_d, surplus_cap)
```

Where:
- `w_sat` (e.g. 0.8) and `w_head` (e.g. 0.2) balance the value of meeting the threshold versus exceeding it.
- `surplus_d = max(C_i[d] − τ_d, 0)`
- Division by `|R_j^pref|` produces an average per-dimension quality

**Design note:** This addresses the flaw where a node exactly meeting a preferred threshold (surplus = 0) would previously receive a score of 0. Now it correctly receives a score equal to `w_sat`.

### 7.5 Full match computation

```
compute_full_match(C_i, R_j, age_s) → MatchResult:
    confidence = compute_confidence(age_s)
    
    IF confidence == 0.0:
        RETURN MatchResult {
            eligible: false,
            quality: 0.0,
            confidence: 0.0,
            weighted_quality: 0.0,
            dimension_details: {},
            unmet_required: [ALL d IN R_j^req],
            missing_dimensions: [ALL d IN R_j^req]
        }
    
    # Phase 1: Eligibility
    eligible = check_eligibility(C_i, R_j^req)
    
    # Build per-dimension details (for ALL dimensions, required and preferred)
    dimension_details = {}
    unmet_required = []
    missing_dims = []
    
    FOR EACH d IN R_j^req ∪ R_j^pref:
        IF d NOT IN C_i:
            missing_dims.append(d)
            dimension_details[d] = DimensionResult {
                met: false, surplus: 0.0,
                node_value: ABSENT, task_value: R_j[d],
                required: (d IN R_j^req), compatible: false
            }
            IF d IN R_j^req:
                unmet_required.append(d)
        ELSE:
            result = compare(C_i[d], R_j[d])   # Dispatches by type
            dimension_details[d] = DimensionResult {
                met: result.met,
                surplus: result.surplus IF exists ELSE 0.0,
                node_value: C_i[d],
                task_value: R_j[d],
                required: (d IN R_j^req),
                compatible: result.compatible IF exists ELSE result.met
            }
            IF (d IN R_j^req) AND (NOT result.met):
                unmet_required.append(d)
    
    # Phase 2: Quality (only meaningful if eligible)
    IF eligible:
        quality = compute_match_quality(C_i, R_j^pref)
    ELSE:
        quality = 0.0
    
    weighted_quality = quality × confidence
    
    RETURN MatchResult {
        eligible: eligible,
        quality: quality,
        confidence: confidence,
        weighted_quality: weighted_quality,
        dimension_details: dimension_details,
        unmet_required: unmet_required,
        missing_dimensions: missing_dims
    }
```

---

## 8. PLAIN-ENGLISH ALGORITHM

### Step 1: Compute confidence

If this is a self-evaluation, confidence = 1.0.
If this is a remote evaluation, compute how old the capability report is.
Apply exponential decay: confidence = e^(−age / half_life).
If confidence drops below the floor, stop — the report is too stale to use.

### Step 2: Eligibility gate (required dimensions)

Walk through every required dimension in the task.
For each dimension:
- If the node's capability report has no entry for this dimension, the node FAILS.
- If the node has the dimension, compare it against the task threshold using the appropriate type-aware comparison.
- If the comparison says "not met," the node FAILS.

One failure in any required dimension → the node is ineligible. Do not continue to quality scoring. Record which dimensions were unmet (this information feeds into 005 for coalition formation — another node may cover the gap).

### Step 3: Quality scoring (preferred dimensions)

If the node passed eligibility, now score how well it meets preferred dimensions.
Walk through every preferred dimension:
- If the node doesn't have this dimension, it contributes 0 to quality.
- For BOOLEAN/CATEGORICAL: met = 1.0, not met = 0.0.
- For CONTINUOUS/CAPACITY: compute surplus as a fraction of the threshold, capped at 1.0.

Average the per-dimension scores. This produces quality ∈ [0, 1].

### Step 4: Apply confidence

Multiply quality by confidence to get weighted_quality.
Self-evaluations retain full quality. Remote evaluations are discounted.

### Step 5: Package result

Return a MatchResult containing eligibility, quality, confidence, weighted_quality, per-dimension breakdowns, and lists of unmet and missing dimensions.

This result is consumed by:
- 004 (allocation bids) — uses weighted_quality to rank candidates
- 005 (coalition formation) — uses unmet_required to find complementary partners
- Decision trace — uses dimension_details for explainability

---

## 9. PSEUDOCODE

```python
# ─── Configuration ───────────────────────────────────────────────────
T_HALF         = 30.0    # staleness half-life (seconds)
CONFIDENCE_FLOOR = 0.05  # below this, report is treated as UNKNOWN
SURPLUS_CAP    = 1.0     # max normalized surplus per dimension
W_SAT          = 0.8     # weight given to meeting the threshold
W_HEAD         = 0.2     # weight given to headroom (surplus)

# ─── Type-aware comparison dispatch ──────────────────────────────────

def compare(node_value, task_req):
    """Dispatch to type-specific comparison based on dimension type tag."""
    match task_req.dim_type:
        case BOOLEAN:
            return compare_boolean(node_value, task_req.value)
        case CONTINUOUS:
            return compare_continuous(node_value, task_req.threshold)
        case CAPACITY:
            return compare_capacity(node_value, task_req.threshold)
        case CATEGORICAL:
            return compare_categorical(node_value, task_req.required_set)

def compare_boolean(has, required):
    return CompResult(met=(has == True or required == False))

def compare_continuous(value, threshold):
    met = (value >= threshold)
    surplus = max(value - threshold, 0.0)
    return CompResult(met=met, surplus=surplus)

def compare_capacity(value, threshold):
    met = (value >= threshold)
    surplus = max(value - threshold, 0.0)
    return CompResult(met=met, surplus=surplus)

def compare_categorical(value, required_set):
    compatible = (value in required_set)
    return CompResult(met=compatible, compatible=compatible)

# ─── Staleness ───────────────────────────────────────────────────────

def compute_confidence(age_s):
    if age_s == 0:
        return 1.0
    raw = exp(-age_s / T_HALF)
    if raw < CONFIDENCE_FLOOR:
        return 0.0
    return raw

# ─── Phase 1: Eligibility ───────────────────────────────────────────

def check_eligibility(C_i, R_req):
    """Return True iff C_i meets ALL required dimensions."""
    for d in R_req:
        if d not in C_i:
            return False               # Missing → does not have
        result = compare(C_i[d], R_req[d])
        if not result.met:
            return False               # Below threshold
    return True

# ─── Phase 2: Quality ───────────────────────────────────────────────

def compute_match_quality(C_i, R_pref):
    """Compute quality score over preferred dimensions."""
    if len(R_pref) == 0:
        return 1.0                     # No preferences → perfect
    
    total = 0.0
    for d in R_pref:
        if d not in C_i:
            score_d = 0.0
        else:
            result = compare(C_i[d], R_pref[d])
            if R_pref[d].dim_type in (BOOLEAN, CATEGORICAL):
                score_d = 1.0 if result.met else 0.0
            else:  # CONTINUOUS or CAPACITY
                satisfaction = 1.0 if result.met else 0.0
                if R_pref[d].threshold == 0:
                    headroom = 0.0
                else:
                    headroom = min(result.surplus / R_pref[d].threshold, SURPLUS_CAP)
                score_d = (W_SAT * satisfaction) + (W_HEAD * headroom)
    
        total += score_d
    
    return clamp(total / len(R_pref), 0.0, 1.0)

# ─── Full match ──────────────────────────────────────────────────────

def compute_full_match(C_i, R_j, age_s):
    """
    Main entry point.
    Returns MatchResult with eligibility, quality, confidence,
    per-dimension details, and diagnostic lists.
    """
    confidence = compute_confidence(age_s)
    
    if confidence == 0.0:
        return MatchResult(
            eligible=False, quality=0.0, confidence=0.0,
            weighted_quality=0.0, dimension_details={},
            unmet_required=list(R_j.required.keys()),
            missing_dimensions=list(R_j.required.keys())
        )
    
    # Phase 1
    eligible = check_eligibility(C_i, R_j.required)
    
    # Dimension details
    details = {}
    unmet_req = []
    missing = []
    
    for d in union(R_j.required, R_j.preferred):
        is_required = (d in R_j.required)
        task_spec = R_j.required[d] if is_required else R_j.preferred[d]
        
        if d not in C_i:
            missing.append(d)
            details[d] = DimensionResult(
                dimension=d, dim_type=task_spec.dim_type,
                required=is_required, met=False,
                surplus=0.0, node_value=ABSENT,
                task_value=task_spec, compatible=False
            )
            if is_required:
                unmet_req.append(d)
        else:
            result = compare(C_i[d], task_spec)
            details[d] = DimensionResult(
                dimension=d, dim_type=task_spec.dim_type,
                required=is_required, met=result.met,
                surplus=getattr(result, 'surplus', 0.0),
                node_value=C_i[d], task_value=task_spec,
                compatible=getattr(result, 'compatible', result.met)
            )
            if is_required and not result.met:
                unmet_req.append(d)
    
    # Phase 2
    quality = compute_match_quality(C_i, R_j.preferred) if eligible else 0.0
    weighted_quality = quality * confidence
    
    return MatchResult(
        eligible=eligible,
        quality=quality,
        confidence=confidence,
        weighted_quality=weighted_quality,
        dimension_details=details,
        unmet_required=unmet_req,
        missing_dimensions=missing
    )
```

---

## 10. WORKED EXAMPLE

### 10.1 Scenario setup

**Task:** `mapping_zone_b`

```
mapping_zone_b = {
    required: {
        localization:     { type: CONTINUOUS, threshold: 0.70 },
        sensing_visual:   { type: CONTINUOUS, threshold: 0.60 },
        has_camera:       { type: BOOLEAN,    value: true }
    },
    preferred: {
        lidar:            { type: CONTINUOUS, threshold: 0.80 },
        compute_gpu:      { type: CAPACITY,   threshold: 8.0 TFLOPS },
        model_runtime:    { type: CATEGORICAL, required_set: {"tensorrt", "onnx"} }
    },
    mission_priority: 0.91
}
```

**Node:** `drone_alpha`

```
drone_alpha = {
    localization:     0.85,          # CONTINUOUS
    sensing_visual:   0.91,          # CONTINUOUS
    has_camera:       true,          # BOOLEAN
    lidar:            0.72,          # CONTINUOUS (below preferred threshold)
    compute_gpu:      12.0 TFLOPS,  # CAPACITY
    model_runtime:    "tensorrt",    # CATEGORICAL
    energy:           0.63
}
```

### 10.2 Part (a): Self-evaluation (age_s = 0)

#### Step 1: Confidence
```
age_s = 0 → confidence = 1.0 (self-evaluation)
```

#### Step 2: Eligibility gate — required dimensions

| Dimension | Type | Node value | Threshold | Compare | Met? |
|---|---|---|---|---|---|
| localization | CONTINUOUS | 0.85 | 0.70 | 0.85 ≥ 0.70 | ✅ surplus = 0.15 |
| sensing_visual | CONTINUOUS | 0.91 | 0.60 | 0.91 ≥ 0.60 | ✅ surplus = 0.31 |
| has_camera | BOOLEAN | true | true | true == true | ✅ |

**All required dimensions met → ELIGIBLE**

#### Step 3: Quality scoring — preferred dimensions

| Dimension | Type | Node value | Threshold | Met? | Score calculation | score_d |
|---|---|---|---|---|---|---|
| lidar | CONTINUOUS | 0.72 | 0.80 | ❌ | satisfaction = 0, headroom = 0 | 0.000 |
| compute_gpu | CAPACITY | 12.0 | 8.0 | ✅ | satisfaction = 1, headroom = min(4.0/8.0, 1.0) = 0.5. score = (0.8*1) + (0.2*0.5) | 0.900 |
| model_runtime | CATEGORICAL | "tensorrt" | {"tensorrt","onnx"} | ✅ | "tensorrt" ∈ set | 1.000 |

```
quality = (1/3) × (0.000 + 0.900 + 1.000)
        = (1/3) × 1.900
        = 0.633
```

#### Step 4: Weighted quality
```
weighted_quality = 0.500 × 1.0 = 0.500
```

#### Step 5: Result

```
MatchResult {
    eligible:         true
    quality:          0.633
    confidence:       1.000
    weighted_quality: 0.633
    unmet_required:   []
    missing_dims:     []
}
```

**Interpretation:** drone_alpha can do the task (all hard requirements met). It is a good match — it lacks the preferred lidar threshold but meets the GPU preference with good surplus and has a compatible runtime. Quality = 0.633 means downstream allocators (004) will rank it below a node that also meets the lidar preference.

---

### 10.3 Part (b): Remote evaluation with 45s-old report

Same node, same task, but now a remote evaluator is using a capability report that is 45 seconds old.

#### Step 1: Confidence
```
age_s = 45
confidence = exp(−45 / 30) = exp(−1.5) = 0.223
```

The report is significantly stale. Confidence has dropped to 22.3%.

#### Step 2: Eligibility gate

Same per-dimension comparisons as Part (a) — all required dimensions still show as met based on the report values. But note: the evaluator is trusting a 45-second-old snapshot. The real node may have changed.

**ELIGIBLE** (based on reported values)

#### Step 3: Quality scoring

Same calculation: quality = 0.500

#### Step 4: Weighted quality
```
weighted_quality = 0.500 × 0.223 = 0.112
```

#### Step 5: Result

```
MatchResult {
    eligible:         true
    quality:          0.500
    confidence:       0.223
    weighted_quality: 0.112
    unmet_required:   []
    missing_dims:     []
}
```

**Interpretation:** The match is nominally the same, but the staleness penalty reduces the effective signal from 0.500 to 0.112. If another node has a fresh self-evaluation with weighted_quality = 0.35, the allocator (004) should prefer it — not because it's intrinsically better, but because the evaluator has more confidence in its actual current state.

**Key difference between (a) and (b):**

| Metric | Self-eval (a) | Remote 45s (b) | Ratio |
|---|---|---|---|
| quality | 0.500 | 0.500 | 1.00 |
| confidence | 1.000 | 0.223 | 0.22 |
| weighted_quality | 0.500 | 0.112 | 0.22 |

The staleness penalty is the entire difference. The raw match is identical; the trust in its accuracy is not.

---

## 11. EDGE CASES

### 11.1 Node at 5% battery meets all requirements

**Scenario:** Node's energy = 0.05, but the task does not list energy as a required or preferred dimension.

**Behavior:** 003 reports the node as eligible with full quality for the dimensions the task cares about. 003 does not know or care about energy constraints.

**Why this is correct:** Energy-aware allocation is 004's responsibility. 003 answers "CAN this node do the task based on capabilities?" not "SHOULD it?" A node at 5% battery CAN map a zone if it has the sensors and compute. Whether it SHOULD is a cost and scarcity question.

**Risk:** If energy is genuinely a hard constraint for the task (the mapping zone requires 20 minutes of flight), it should be modeled as a required dimension in R_j, e.g., `energy: { type: CONTINUOUS, threshold: 0.30 }`. This is a task design responsibility (002), not a matching engine responsibility.

### 11.2 Missing dimension

**Scenario:** Task requires `sensing.lidar ≥ 0.6` but node's capability report has no `sensing.lidar` entry.

**Behavior:** The dimension is treated as absent. compare() is never called. The node fails the eligibility gate for this dimension.

```
d = "sensing.lidar"
d NOT IN C_i → return False
```

**Rationale (Assumption A8):** Missing data is not "maybe." In a safety-relevant system, an unreported capability must be treated as unavailable. If a node actually has lidar but didn't report it, the problem is in the node's 001 capability registration, not in the matching engine.

**Diagnostic output:** The dimension appears in both `unmet_required` and `missing_dimensions` lists. This distinction matters for 005 — a missing dimension on one node can potentially be covered by another node in a coalition.

### 11.3 Identical quality ties

**Scenario:** Two nodes produce identical MatchResult: both eligible, both quality = 0.500, both confidence = 1.0.

**Behavior:** 003 returns identical MatchResults. It does not break ties.

**Rationale:** Tie-breaking is 004's responsibility. 004 may break ties using:
- Scarcity cost (which node has more unique capabilities to preserve?)
- Energy efficiency (which node is cheaper to use?)
- Communication cost (which node is closer to the task zone?)
- Arbitrary but deterministic rule (lower node ID wins, for consistency)

003's job is to produce honest, comparable scores. Tie-breaking introduces allocation policy, which is outside scope (Assumption A9).

### 11.4 Severely stale report

**Scenario:** A capability report is 120 seconds old. With t_half = 30:

```
confidence = exp(−120 / 30) = exp(−4) = 0.018
```

This is below confidence_floor (0.05).

**Behavior:** confidence = 0.0. The function returns early:

```
MatchResult {
    eligible: false,
    quality: 0.0,
    confidence: 0.0,
    weighted_quality: 0.0,
    unmet_required: [ALL required dims],
    missing_dimensions: [ALL required dims]
}
```

**Rationale:** A 120-second-old report in a dynamic swarm environment is near-worthless. The node may have depleted its battery, lost a sensor, or crashed. Making allocation decisions based on severely stale data is worse than treating the node as unknown.

**Consequence:** The node is effectively invisible to the matcher until a fresh report arrives. This creates pressure for nodes to broadcast capability updates — a behavior that 003 does not control but that the communication subsystem must support.

### 11.5 Barely-meets (surplus ≈ 0)

**Scenario:** Task requires `localization ≥ 0.70`. Node has `localization = 0.71`.

**Behavior:** The dimension is met. surplus = 0.01. If this is a preferred dimension:

```
score_d = min(0.01 / 0.70, 1.0) = 0.014
```

The node barely contributes quality on this dimension.

**Rationale:** This is correct behavior. A node that barely meets a threshold is less desirable than one with significant headroom, and the quality score reflects that. The eligibility gate treats 0.70 and 0.71 identically (both pass), but quality scoring differentiates them.

**Risk:** In real systems, sensor measurements have noise. A node at 0.71 might actually be at 0.69 due to measurement uncertainty. Handling measurement noise is an open question (Section 14) — v0.1 treats reported values as exact.

### 11.6 Zero-threshold preferred dimension

**Scenario:** A preferred dimension has threshold = 0.0 (e.g., "any amount of lidar is a bonus").

**Behavior:** If the node has any positive value, surplus = value − 0 = value. The score calculation becomes:

```
score_d = min(value / 0.0, 1.0)   # Division by zero!
```

**Mitigation:** The pseudocode (Section 9) handles this:

```python
if R_pref[d].threshold == 0:
    score_d = 1.0 if result.met else 0.0
```

If the threshold is 0, any non-negative value meets it, and the dimension gets full credit (1.0). This avoids division by zero and is semantically correct: "having any amount of this capability is preferred" → if you have it, full marks.

### 11.7 All preferred dimensions missing

**Scenario:** Task has three preferred dimensions. Node's capability report contains none of them.

**Behavior:** score_d = 0.0 for all three. quality = 0.0. The node is eligible (it passed required dims) but has zero quality.

**Interpretation:** The node can technically do the task but brings no preferred capabilities. The allocator (004) will strongly prefer any node with nonzero quality, but if no better option exists, this node is still a valid fallback. This supports HESK's graceful degradation philosophy.

---

## 12. FAILURE MODES

### 12.1 Stale report produces false eligibility

**Problem:** A node's report says `localization = 0.85` but the node's GPS degraded 20 seconds ago and true localization is now 0.30. The matcher declares the node eligible.

**Mitigation:** Staleness decay reduces confidence but cannot detect specific dimension changes. The responsibility chain is:
1. The node itself should broadcast updated capability state when significant changes occur (event-triggered updates).
2. The allocator (004) should prefer nodes with fresher reports (higher weighted_quality).
3. After task assignment, the executing node should re-validate its own capabilities via self-evaluation before beginning execution.

003 cannot solve this alone. It correctly models uncertainty through confidence decay, but it cannot detect WHICH dimensions changed.

### 12.2 Dimension type mismatch

**Problem:** A task defines `compute_gpu` as CONTINUOUS (normalized) but a node reports it as CAPACITY (absolute TFLOPS). The comparison function receives incompatible units.

**Mitigation:** This is a 001/002 schema validation problem. The dimension namespace (Assumption A2) must enforce consistent type tags. If a type mismatch is detected, 003 should reject the comparison and flag the dimension as `ERROR` rather than silently producing a nonsensical result.

### 12.3 Adversarial or faulty capability reporting

**Problem:** A node reports `sensing_visual = 0.99` but its actual camera quality is 0.20. 003 will incorrectly declare it eligible and highly-scored.

**Mitigation:** 003 does not validate truthfulness. It trusts the 001 schema. Detecting faulty or adversarial reports requires cross-validation (did the node's previous task results match its claimed capabilities?), which is outside 003's scope. For v0.1, honest reporting is assumed. Byzantine fault tolerance is a future research direction.

### 12.4 Clock disagreement corrupts staleness

**Problem:** Node A's clock says 14:00:00. Node B's report says t_gen = 14:00:30 (30 seconds in A's future due to clock drift). Node A computes age_s = −30, which is nonsensical.

**Mitigation:** For v0.1, enforce age_s = max(t_now − t_gen, 0). Negative ages are clamped to 0 (treated as perfectly fresh). This is incorrect but safe — it overestimates trust rather than underestimating. Proper clock synchronization is a 007/008 concern.

### 12.5 Dimension explosion

**Problem:** A node reports 200 capability dimensions. A task requires 3. The comparison is efficient (O(|R_j|) not O(|C_i|)), but the DimensionResult dictionary is large.

**Mitigation:** 003 only iterates over R_j^req ∪ R_j^pref, not over all of C_i. Unrequired dimensions are ignored. The output size is proportional to |R_j|, not |C_i|.

---

## 13. INVARIANTS

**I-003.1: Two-phase separation.**
Eligibility and quality are never conflated. A node with quality = 0.0 on preferred dimensions but all required dimensions met is ELIGIBLE. A node with quality = 1.0 on preferred dimensions but one required dimension unmet is INELIGIBLE. These two cases are categorically different.

**I-003.2: Missing = absent.**
If a required dimension d is absent from C_i, the node is ineligible for that dimension. No exception. No inference. No "maybe the node has it but didn't report it." (Assumption A8)

**I-003.3: Type-aware comparison.**
BOOLEAN dimensions are compared as booleans, CONTINUOUS as ordered scalars, CAPACITY as ordered absolute values, CATEGORICAL as set membership. No dimension type is ever compared using another type's logic. (Section 7.2)

**I-003.4: Confidence bounds.**
confidence ∈ {0.0} ∪ [confidence_floor, 1.0]. It is never negative. It is exactly 1.0 for self-evaluation. It is exactly 0.0 for reports below confidence_floor. (Section 7.3)

**I-003.5: Quality bounds.**
quality ∈ [0.0, 1.0]. weighted_quality ∈ [0.0, 1.0]. No MatchResult ever produces values outside this range. (Section 7.4)

**I-003.6: No allocation decisions.**
003 never decides whether a node SHOULD execute a task. It only determines WHETHER IT CAN and HOW WELL IT MATCHES. The SHOULD decision belongs to 004. (Assumption A9)

**I-003.7: No global state access.**
003 operates on locally available information only. It reads C_i (own state or received report) and R_j (task definition). It never queries a global capability registry, a central coordinator, or a simulation oracle. (Construction Guide, Invariant 1)

**I-003.8: Deterministic output.**
Given the same (C_i, R_j, age_s) triple and the same configuration parameters, compute_full_match always produces the same MatchResult. There is no randomness or hidden state.

**I-003.9: Staleness monotonicity.**
For a fixed (C_i, R_j), as age_s increases, weighted_quality weakly decreases. Confidence never increases with age. Older reports never produce higher-confidence results.

---

## 14. OPEN QUESTIONS

### OQ-003.1: Dimension weighting

v0.1 uses unweighted average: all preferred dimensions contribute equally to quality.

This may be wrong. If a task strongly prefers GPU but mildly prefers lidar, the two should not have equal weight. Possible approaches:

- Task-defined weights: R_j^pref includes a weight w_d per dimension. quality = Σ(w_d × score_d) / Σ(w_d).
- Importance ranking: Dimensions are ordered by priority; quality uses a weighted decay (first dimension counts more).
- Leave to 004: Let the allocator weight dimensions differently.

**Risk of premature weighting:** Adding weights before understanding their impact may create tuning nightmares. v0.1 defers this intentionally.

### OQ-003.2: Minimum quality threshold

Should 003 define a minimum acceptable quality below which a match is "technically eligible but operationally useless"?

Example: A node meets all required dims but has quality = 0.02 (barely any preferred capability). Is this worth reporting to 004?

**Option A:** 003 reports it; 004 decides if it's worth allocating.
**Option B:** 003 applies a quality_floor and marks matches below it as "eligible but low quality."

v0.1 uses Option A — 003 reports everything and lets 004 filter.

### OQ-003.3: Should 003 flag opportunity cost?

Currently, 003 does not know about scarcity. If drone_alpha has a unique thermal sensor and is matched to a non-thermal task, 003 produces a normal MatchResult with no warning.

Should 003 include a field like `unique_capabilities_at_risk: [thermal]`? This would require 003 to know the swarm-wide capability distribution, which violates its local-only principle.

**Current answer:** No. Scarcity analysis is 004's job. 003 stays capability-local.

### OQ-003.4: Measurement noise and confidence intervals

v0.1 treats all reported values as exact. In reality, `sensing_visual = 0.71` might be 0.71 ± 0.05. Should 003 accept confidence intervals and compare distributions rather than point values?

This significantly increases complexity. Deferred to v0.2+.

### OQ-003.5: Staleness half-life tuning

t_half = 30s is a reasonable default, but:
- High-speed combat drones change state rapidly → t_half = 10s?
- Slow infrastructure inspection rovers change state slowly → t_half = 120s?
- Should t_half be per-dimension? (Battery depletes faster than compute availability changes.)

Per-dimension half-lives add complexity. Deferred.

### OQ-003.6: Partial eligibility for degraded execution

Currently, eligibility is binary: ALL required dims or nothing. But HESK's core philosophy is graceful degradation (Scope §5).

Should 003 report a "partial eligibility" score for nodes that miss one required dimension by a small margin?

Example: Task requires `localization ≥ 0.70`. Node has `localization = 0.65`. Is this a 93%-eligible match that 006 (graceful degradation) might accept for a degraded mapping mode?

**Current answer:** No. 003 enforces the hard gate. If degraded execution is acceptable, the task definition (002) should model it — either by lowering the required threshold or by having a separate degraded-mode task variant. 003 does not second-guess task requirements.

### OQ-003.7: Multi-value dimensions

Some capabilities may have multiple values (e.g., a node with both RGB and thermal cameras for `sensing`). How should multi-value dimensions be matched?

Deferred. v0.1 assumes one value per dimension. Multi-sensor nodes model each sensor as a separate dimension (e.g., `sensing.rgb`, `sensing.thermal`).

---

## 15. BASELINE FOR COMPARISON

### 15.1 Baseline: Dot product similarity

The simplest imaginable matching approach: flatten all capability dimensions and task requirements into equal-length vectors and compute their dot product (or cosine similarity).

```
baseline_match(C_i, R_j):
    dims = union(keys(C_i), keys(R_j))
    c_vec = [C_i.get(d, 0.0) for d in dims]
    r_vec = [R_j.get(d, 0.0) for d in dims]
    score = dot(c_vec, r_vec) / (norm(c_vec) * norm(r_vec))
    return score
```

### 15.2 Why the dot product baseline fails

The dot product baseline has three specific failures that motivate 003's design:

#### Failure 1: BOOLEAN dimensions are averaged away

Consider a task requiring `has_camera = true` and `sensing_visual ≥ 0.6`.

A node WITHOUT a camera but with `sensing_visual = 0.95` and `compute = 0.99` produces a high dot product score because the numerical strength of other dimensions drowns out the binary failure.

In a dot product world, `has_camera = false` is just a zero in one vector position — it reduces the score slightly but does not gate eligibility. The node gets a reasonable score and may be allocated.

**003's solution:** BOOLEAN dimensions participate in the eligibility gate. If `has_camera = false` and the task requires it, the node is immediately rejected regardless of all other dimensions. The boolean is never "averaged away."

#### Failure 2: CAPACITY normalization loses meaning

GPU compute may be measured in TFLOPS (e.g., 8.0, 12.0, 16.0). If naively placed in a [0, 1] normalized vector alongside `sensing_visual = 0.91`, the absolute values distort the similarity.

Worse: normalizing 12.0 TFLOPS to some [0, 1] range requires knowing the max TFLOPS across all nodes — a global statistic that no single node has (Construction Guide, Invariant 1).

**003's solution:** CAPACITY comparisons operate in absolute units. Surplus is normalized by the task threshold (surplus / threshold), not by the swarm maximum. This is locally computable and semantically meaningful: "how much headroom does this node have relative to what the task needs?"

#### Failure 3: CATEGORICAL dimensions are numerically incomparable

`model_runtime = "tensorrt"` and `required = {"tensorrt", "onnx"}`. How do you put "tensorrt" into a numeric vector? Common approaches:

- One-hot encoding: Explodes dimensionality. A dot product between one-hot vectors is either 0 or 1 — no gradation, but also no gate.
- Hash to float: Meaningless numerically.
- Ignore: The dimension is silently dropped from matching.

**003's solution:** CATEGORICAL dimensions use set-membership comparison. The result is binary (compatible or not), participates in the eligibility gate if required, and contributes 0 or 1 to quality scoring if preferred. No numeric encoding is needed or attempted.

### 15.3 Expected comparison outcomes

| Scenario | Dot product | 003 |
|---|---|---|
| Node lacks camera, high other scores | High score (dangerous) | Ineligible (correct) |
| Node has compatible runtime, moderate other scores | Moderate score (uninterpretable) | Eligible + runtime contributes 1.0 to quality (interpretable) |
| Node with 12 TFLOPS vs 8 required | Score depends on normalization scheme | surplus = 4.0, score_d = 0.5 (locally computed) |
| 45s-old report | No staleness concept | confidence = 0.223, weighted_quality discounted |
| Missing dimension (no lidar entry) | Zero in vector (weak penalty) | Missing = absent → ineligible if required (strong gate) |

### 15.4 When dot product is acceptable

For early rapid prototyping with only CONTINUOUS dimensions, no staleness, and no categorical compatibility, a dot product is a reasonable first pass. It fails as soon as the system encounters real heterogeneity — which is HESK's foundational design assumption (Scope §2).

---

## Appendix A: Decision Trace Format

For Construction Guide Problem 25 compliance, every MatchResult should be loggable as a human-readable trace:

```
MATCH TRACE: drone_alpha ↔ mapping_zone_b
  Context: self-evaluation
  Age: 0s | Confidence: 1.000

  ELIGIBILITY GATE (required):
    localization     CONTINUOUS  0.85 ≥ 0.70  ✅  surplus=0.15
    sensing_visual   CONTINUOUS  0.91 ≥ 0.60  ✅  surplus=0.31
    has_camera       BOOLEAN     true == true  ✅
  → ELIGIBLE

  QUALITY SCORING (preferred):
    lidar            CONTINUOUS  0.72 < 0.80   ❌  score=0.000
    compute_gpu      CAPACITY    12.0 ≥ 8.0    ✅  score=0.500
    model_runtime    CATEGORICAL tensorrt ∈ {tensorrt,onnx}  ✅  score=1.000
  → quality = (0.000 + 0.500 + 1.000) / 3 = 0.500

  FINAL: eligible=true  quality=0.500  confidence=1.000  weighted=0.500
```

This trace format is not part of the algorithm's computational logic. It is an observability requirement that any implementation of 003 should support.

---

## Appendix B: Relationship to Adjacent Algorithms

```
001 Capability Model          002 Task Model
        │                            │
        ▼                            ▼
    ┌───────────────────────────────────┐
    │       003 Capability Matching      │
    │                                   │
    │  check_eligibility(C_i, R_j^req)  │
    │  compute_match_quality(C_i,R_j^p) │
    │  compute_full_match(C_i,R_j,age)  │
    └────────────┬──────────────────────┘
                 │
        ┌────────┼─────────┐
        ▼        ▼         ▼
      004      005       006
   Scarcity  Coalition  Graceful
   Alloc.    Formation  Degradation

  004 reads: eligible, weighted_quality, dimension_details
      → produces allocation bids combining match quality with cost signals
  
  005 reads: eligible (per-dim), unmet_required, missing_dimensions
      → finds complementary nodes whose capabilities cover gaps
  
  006 reads: quality, missing_dimensions
      → determines if degraded task execution is feasible
```

003 is intentionally narrow. It answers two questions and delegates everything else. This narrowness is a feature — it keeps the algorithm testable, explainable, and composable.
