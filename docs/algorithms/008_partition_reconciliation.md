# 008 — Partition Reconciliation

> **Status:** v0.1 draft — capstone algorithm  
> **Depends on:** ALL preceding algorithms (001–007)  
> **Consumed by:** Runtime (this is the final conflict-resolution layer)  
> **Prior art:** Bayou anti-entropy [Terry et al., 1995], CRDT convergence [Shapiro et al., 2011], Merkle trees for state comparison [Merkle, 1987]

---

## 1. PROBLEM

### 1.1 Core question

> When two sub-swarms that were unable to communicate (partitioned) reconnect, how do they merge their independently-evolved state — assignments, observations, visited zones, node health records — into a single consistent world-view, without losing information, without silently overwriting concurrent decisions, and without requiring a central authority?

### 1.2 Why partitions are normal in HESK

Partitions are NOT exceptional failures.  They are a standard operating mode for swarms (HESK Scope §7, Construction Guide Problem 7).

Causes include:
- Physical distance exceeding radio range
- Terrain obstruction (building, hill)
- Electromagnetic interference (e.g., near power lines)
- Node movement separating sub-groups
- Relay node failure splitting the network

During a partition, each sub-swarm continues to operate independently.  Nodes make decisions, assign tasks, degrade services, update their local ledgers — all without knowing what the other partition is doing.

When the partition heals (nodes move back into range, relay recovers), the sub-swarms must reconcile their divergent states.

### 1.3 Why reconciliation is hard

Three concrete difficulties:

**1. Conflicting exclusive assignments.**  Both partitions may have independently assigned the same task to different nodes.  Alpha assigned mapping to node_3.  Beta assigned mapping to node_5.  Both are currently executing.  Who "wins"?  Neither — the resolution must consider which executor has made more progress, has better match quality, and serves higher overall utility.

**2. NOT "latest wins."**  A stale but high-confidence direct observation may be more trustworthy than a recent low-confidence relay.  Wall-clock comparison alone is insufficient due to clock drift and the Lamport clock limitation (inability to distinguish concurrent from sequentially-ordered events).

**3. Reconciliation must be deterministic.**  If Node 2 from Alpha and Node 4 from Beta independently process the same pair of divergent event logs, they MUST arrive at the same resolution.  Otherwise, reconciliation itself creates new inconsistency.  Determinism means: given the same inputs, any node computes the same output.  No randomness, no local preference, no negotiation.

### 1.4 What this algorithm must understand

Partition reconciliation is the capstone — it must understand EVERY state type from the preceding algorithms:

| State type | From algorithm | Reconciliation behavior |
|------------|---------------|------------------------|
| SET_LIKE (visited_zones, discovered_targets) | 007 | Union — always convergent, no conflict |
| COUNTER (tasks_completed) | 007 | Max — always convergent, no conflict |
| EXCLUSIVE_OWNERSHIP (task_owner.X) | 007, 004, 006 | HARD CASE — concurrent assignments are conflicts |
| OBSERVATIONAL (target_position) | 007 | Preserve both with provenance |
| RESOURCE (node_X.battery) | 007, 001 | Most recent observation (drift-guarded) |
| MISSION_POLICY (priority_overrides) | 007, 002 | Higher authority wins |

---

## 2. DEFINITIONS

### 2.1 Shared notation

| Symbol | Meaning |
|--------|---------|
| n_i | Node i |
| L_i | Local ledger of node i (from 007) |
| λ_i | Lamport clock of node i |
| V_i | Version vector (knowledge frontier) of node i |
| Δ_max | Maximum assumed wall-clock drift (seconds) |
| P_α | Partition Alpha (sub-swarm) |
| P_β | Partition Beta (sub-swarm) |

### 2.2 ReconnectionEvent

```
ReconnectionEvent:
  detecting_node:     NodeId              # the node that detected reconnection
  remote_node:        NodeId              # the node from the other partition
  detection_time:     float               # wall time of detection
  detecting_clock:    int                 # local Lamport clock at detection
  remote_version_vec: {NodeId: int}       # remote node's version vector
  partition_duration: float               # estimated duration of the partition (seconds)
```

### 2.4 Conflict

```
Conflict:
  key:                string              # the ledger key in conflict
  local_entry:        LedgerEntry         # this node's current value
  remote_entry:       LedgerEntry         # the other node's value
  semantic_type:      StateSemanticType   # the entry's semantic type
  resolution:         Resolution or None  # filled after resolution
```

### 2.5 Resolution

```
Resolution:
  strategy:           string              # which resolution rule was applied
  winning_value:      any                 # the resolved value
  winning_source:     NodeId              # which partition's value won
  reason:             string              # human-readable explanation
  side_effects:       [SideEffect]        # additional actions triggered
```

### 2.6 ReconciliationTrace

For decision explainability:

```
ReconciliationTrace:
  reconnection:       ReconnectionEvent
  divergence:         DivergencePoint
  conflicts_found:    int
  conflicts_resolved: int
  resolution_details: [Conflict]          # with resolutions filled
  entries_merged:     int                 # total entries updated
  entries_unchanged:  int                 # entries that were already consistent
  duration_ms:        float               # time taken for reconciliation
```

### 2.7 Per-type resolution rules

This table is the core of Algorithm 008.  It governs how EVERY conflict is resolved deterministically.

| Semantic type | Resolution rule | Deterministic? | Convergent? |
|---------------|----------------|---------------|-------------|
| SET_LIKE | Union of both values | Yes | Yes (CRDT) |
| COUNTER | Max of both values | Yes | Yes (CRDT) |
| EXCLUSIVE_OWNERSHIP | See §7.3 (progress → quality → node_id tiebreak) | Yes | Yes (deterministic) |
| OBSERVATIONAL | Keep both values with provenance | Yes | Yes (append-only) |
| RESOURCE | Most recent observation, drift-guarded (§7.4) | Yes | Yes (within drift bounds) |
| MISSION_POLICY | Higher authority value wins | Yes | Yes |

---

## 3. ASSUMPTIONS

**A1. Reconnection is detectable.**  When a previously-unreachable node becomes reachable again, this is detected (e.g., by receiving a heartbeat or message from a node marked SUSPECTED_UNREACHABLE in the ledger).

**A2. The reconciliation algorithm is deterministic.**  Given the same inputs (local ledger, remote events), any node computes the same resolutions.  This is ESSENTIAL — it means both reconnecting nodes can independently reconcile and arrive at the same state without additional negotiation.

**A3. No Byzantine failures.**  Nodes do not fabricate events or lie about their state.  Failures are crash-stop or omission only.

**A4. Wall-clock drift is bounded (Δ_max).**  Same assumption as 007.

**A5. Event logs are available for the partition duration.**  If the partition lasted longer than the event log retention window (007, §7.6), reconciliation falls back to full ledger comparison.

**A6. Reconciliation is pairwise.**  When two nodes from different partitions reconnect, they reconcile their ledgers directly.  If more than two partitions exist, each pair reconciles independently.  The deterministic resolution rules ensure that multi-pair reconciliation converges.

**A7. Task progress information is available.**  For EXCLUSIVE_OWNERSHIP conflicts (dual task assignment), the algorithm needs to compare executor progress.  v0.1 assumes each node tracks and reports its task execution progress as a fraction ∈ [0, 1].

---

## 4. INPUTS

### At the detecting node

| Input | Source | Description |
|-------|--------|-------------|
| local_ledger | Algorithm 007 | This node's full ledger state |
| local_event_log | Algorithm 007 | This node's event history |
| remote_node_id | Reconnection detection | Which node from the other partition |

### From the remote node (exchanged during protocol)

| Input | Source | Description |
|-------|--------|-------------|
| remote_clock | First exchange message | Remote node's current Lamport clock |
| remote_events_since_divergence | Event exchange phase | Events the remote node recorded since the divergence point |
| remote_ledger_entries | If full comparison needed | Remote node's current ledger entries for conflicting keys |

---

## 5. LOCALLY AVAILABLE INFORMATION

### KNOWN LOCALLY
- Own ledger L_i — complete current state
- Own event log — history of state changes (within retention window)
- Own partition history — which nodes were reachable/unreachable and when
- Own task assignments and execution progress

### RECEIVED VIA MESSAGES (during reconciliation protocol)
- Remote node's Lamport clock (from initial exchange)
- Remote node's event summary or events since divergence
- Remote node's ledger entries for conflicting keys
- Remote node's task execution progress (for EXCLUSIVE_OWNERSHIP resolution)

### INFERRED
- Divergence point — computed from clock comparison and event log comparison
- Set of conflicting keys — computed by comparing local entries with remote events/entries
- Conflict resolutions — computed deterministically from the resolution rules

### UNKNOWN
- State of nodes in STILL-UNREACHABLE partitions (may exist beyond both reconnecting partitions)
- Events that occurred on the remote side but were already compacted from their event log
- Whether the remote node's ledger is fully up-to-date with all nodes in ITS partition (it may also be partially stale)

---

## 6. OUTPUT

### Primary output: ReconciliationTrace (§2.6)

Contains:
- How many conflicts were found and resolved
- Resolution details for each conflict
- Total entries merged
- Time taken

### Side effects

- **Ledger updates:** Both nodes update their local ledgers to reflect resolved state
- **Broadcast:** Both nodes broadcast reconciliation results to their respective sub-swarms
- **Task actions:** EXCLUSIVE_OWNERSHIP resolutions may trigger:
  - Task reassignment (the losing executor is instructed to stop)
  - Coalition dissolution or reformation
  - Degradation tier changes (merged swarm may enable higher tiers)

---

## 7. DECISION RULE

### 7.1 Knowledge Exchange

Two nodes exchange their version vectors to determine which events are unseen by the other side. This replaces the naive scalar "divergence point" which fails in non-linear event histories:

```
def get_unseen_events(local_log, remote_version_vector):
    """
    Return all local events that the remote side has not yet seen.
    """
    unseen = []
    for event in local_log:
        remote_known_seq = remote_version_vector.get(event.origin_node, 0)
        if event.origin_seq > remote_known_seq:
            unseen.append(event)
    return unseen
```

### 7.2 Conflict detection

After exchanging unseen events based on version vectors, identify keys that were modified concurrently on BOTH sides:

```
def detect_conflicts(local_ledger, local_events, remote_events):
    """
    Find keys modified on both sides since divergence.
    Returns list of Conflict objects.
    """
    local_modified_keys = {e.key for e in local_events}
    remote_modified_keys = {e.key for e in remote_events}
    
    potentially_conflicting = local_modified_keys & remote_modified_keys
    
    conflicts = []
    for key in potentially_conflicting:
        local_entry = local_ledger.entries[key]
        remote_entry = reconstruct_entry(remote_events, key)
        
        # SET_LIKE and COUNTER never conflict (merge is always valid)
        if local_entry.semantic_type in (SET_LIKE, COUNTER):
            continue  # handled by merge, no conflict
        
        # OBSERVATIONAL doesn't conflict (both observations preserved)
        if local_entry.semantic_type == OBSERVATIONAL:
            continue
        
        # EXCLUSIVE_OWNERSHIP, RESOURCE, MISSION_POLICY may conflict
        if local_entry.value != remote_entry.value:
            conflicts.append(Conflict(
                key=key,
                local_entry=local_entry,
                remote_entry=remote_entry,
                semantic_type=local_entry.semantic_type
            ))
    
    return conflicts
```

### 7.3 EXCLUSIVE_OWNERSHIP resolution — the hard case

This is the most important resolution rule.  Two partitions independently assigned the same task to different executors.

**Resolution protocol (deterministic):**

```
def resolve_exclusive_ownership(conflict):
    """
    Resolve dual ownership of a task.
    Deterministic: given the same inputs, any node produces the same result.
    
    Resolution cascade:
    1. Higher execution progress wins
    2. If equal progress: higher match quality wins
    3. If equal quality: lower node_id wins (arbitrary but deterministic)
    """
    local = conflict.local_entry
    remote = conflict.remote_entry
    
    # HESK uses stable attributes for conflict resolution to ensure convergence.
    # Dynamic properties like progress must NOT be used because progress changes,
    # destroying associativity and leading to non-convergent merge cycles.
    
    # Step 1: Compare original match quality at time of assignment
    # Match quality is stable and reflects the intended utility optimization
    local_quality = get_match_quality(local.value, conflict.key)
    remote_quality = get_match_quality(remote.value, conflict.key)
    
    QUALITY_EPSILON = 0.05  # within 5% is considered "equal"
    
    if abs(local_quality - remote_quality) > QUALITY_EPSILON:
        if local_quality > remote_quality:
            winner = local
            loser = remote
            reason = f"Higher match quality: {local.value} at {local_quality:.2f}"
        else:
            winner = remote
            loser = local
            reason = f"Higher match quality: {remote.value} at {remote_quality:.2f}"
    else:
        # Step 2: Deterministic tiebreak using immutable event properties
        # Origin timestamp + node_id tie-breaker
        if local.wall_time < remote.wall_time:
            winner = local
            loser = remote
            reason = f"Earlier assignment: {local.wall_time} < {remote.wall_time}"
        elif remote.wall_time < local.wall_time:
            winner = remote
            loser = local
            reason = f"Earlier assignment: {remote.wall_time} < {local.wall_time}"
        else:
            if local.value < remote.value:
                winner = local
                loser = remote
                reason = f"Tiebreak: lower node_id {local.value} < {remote.value}"
            else:
                winner = remote
                loser = local
                reason = f"Tiebreak: lower node_id {remote.value} < {local.value}"
    
    return Resolution(
        strategy="EXCLUSIVE_OWNERSHIP_CASCADE",
        winning_value=winner.value,
        winning_source=winner.source_node,
        reason=reason,
        side_effects=[
            SideEffect(type=RELEASE_EXECUTOR, target=loser.value, task=conflict.key),
            SideEffect(type=NOTIFY_WINNER, target=winner.value, task=conflict.key)
        ]
    )
```

**Why this order (progress → quality → node_id)?**

1. **Progress first:** An executor at 60% completion has invested significant resources.  Discarding its work to switch to a 10% executor wastes energy and time.
2. **Quality second:** If both executors are at similar progress, the one with better capability match will likely produce higher-quality results.
3. **Node_id last:** A purely deterministic tiebreak for the rare case where progress and quality are equal.  The specific choice (lower node_id wins) is arbitrary but consistent.

### 7.4 RESOURCE resolution

For RESOURCE-type entries (e.g., node status, battery level):

```
def resolve_resource(conflict):
    """Most recent observation wins, with drift guard."""
    local = conflict.local_entry
    remote = conflict.remote_entry
    
    time_diff = remote.wall_time - local.wall_time
    
    if time_diff > Δ_max:
        # Remote clearly more recent
        return Resolution(
            strategy="RESOURCE_RECENCY",
            winning_value=remote.value,
            winning_source=remote.source_node,
            reason=f"Remote observation is {time_diff:.1f}s newer (beyond drift margin)"
        )
    elif time_diff < -Δ_max:
        # Local clearly more recent
        return Resolution(
            strategy="RESOURCE_RECENCY",
            winning_value=local.value,
            winning_source=local.source_node,
            reason=f"Local observation is {-time_diff:.1f}s newer (beyond drift margin)"
        )
    else:
        # Within drift margin — use provenance quality
        local_score = provenance_score(local)
        remote_score = provenance_score(remote)
        
        if local_score >= remote_score:
            return Resolution(
                strategy="RESOURCE_PROVENANCE",
                winning_value=local.value,
                winning_source=local.source_node,
                reason=f"Within drift margin; local provenance score {local_score:.2f} >= remote {remote_score:.2f}"
            )
        else:
            return Resolution(
                strategy="RESOURCE_PROVENANCE",
                winning_value=remote.value,
                winning_source=remote.source_node,
                reason=f"Within drift margin; remote provenance score {remote_score:.2f} > local {local_score:.2f}"
            )

def provenance_score(entry):
    """Score provenance quality: DIRECT > RELAYED > INFERRED, modified by confidence."""
    type_score = {DIRECT: 1.0, RELAYED: 0.7, INFERRED: 0.5}
    return type_score[entry.provenance.observation_type] * entry.confidence
```

### 7.5 MISSION_POLICY resolution

```
def resolve_mission_policy(conflict):
    """Higher authority wins."""
    local_auth = conflict.local_entry.provenance.authority_level
    remote_auth = conflict.remote_entry.provenance.authority_level
    
    # Lower authority_level number = higher authority
    if local_auth <= remote_auth:
        return Resolution(
            strategy="MISSION_POLICY_AUTHORITY",
            winning_value=conflict.local_entry.value,
            reason=f"Local authority level {local_auth} <= remote {remote_auth}"
        )
    else:
        return Resolution(
            strategy="MISSION_POLICY_AUTHORITY",
            winning_value=conflict.remote_entry.value,
            reason=f"Remote authority level {remote_auth} < local {local_auth}"
        )
```

---

## 8. PLAIN-ENGLISH ALGORITHM

### Partition Reconciliation Protocol

1. **DETECT RECONNECTION.**  Node A receives a message (heartbeat, state update) from Node B.  A's ledger had Node B marked as SUSPECTED_UNREACHABLE.  This is a reconnection event.

2. **EXCHANGE CLOCK SUMMARIES.**  A sends B: {my_clock: λ_A, my_event_checkpoints: [...]}. B does the same.  Both nodes compute the divergence point — the last Lamport clock value where their logs agree.

3. **EXCHANGE EVENTS SINCE DIVERGENCE.**  A sends B all events with clock > λ_div.  B does the same.  If event logs have been compacted past the divergence point, fall back to full ledger exchange.

4. **MERGE CONVERGENT TYPES.**  For SET_LIKE and COUNTER entries: apply union/max respectively.  These are conflict-free and always converge.  For OBSERVATIONAL: append both sides' observations (deduplicate by event_id).

5. **DETECT CONFLICTS.**  For EXCLUSIVE_OWNERSHIP, RESOURCE, and MISSION_POLICY entries: identify keys where both sides have different values.

6. **RESOLVE CONFLICTS DETERMINISTICALLY.**  Apply the resolution rules (§7.3, §7.4, §7.5) to each conflict.  Both Node A and Node B independently compute the SAME resolutions because the rules are deterministic given the same inputs.

7. **APPLY RESOLUTIONS.**  Both nodes update their ledgers with the resolved values.  Side effects (e.g., releasing a losing executor) are queued for execution.

8. **BROADCAST TO SUB-SWARMS.**  Node A broadcasts the reconciliation results to all nodes in its former sub-swarm.  Node B does the same.  This ensures all nodes converge, not just the two that reconnected.

9. **EXECUTE SIDE EFFECTS.**  Release losing executors, notify winners, trigger re-evaluation of degradation tiers (the merged swarm may be able to operate at higher tiers than either partition alone).

10. **LOG TRACE.**  Record the full reconciliation trace for explainability and debugging.

---

## 9. PSEUDOCODE

```python
def handle_reconnection(local_ledger, remote_node_id, remote_message):
    """
    Main entry point for partition reconciliation.
    Called when a previously-unreachable node is detected as reachable.
    
    Deterministic: given the same inputs, any node produces the same result.
    No global state is accessed.
    """
    # Step 1: Confirm reconnection
    reconnection = ReconnectionEvent(
        detecting_node=local_ledger.node_id,
        remote_node=remote_node_id,
        detection_time=local_wall_time(),
        detecting_clock=local_ledger.lamport_clock,
        remote_clock=remote_message.sender_clock
    )
    
    # Step 2: Exchange version vectors
    remote_version_vector = remote_message.version_vector
    
    # Step 3: Exchange unseen events using knowledge frontiers
    local_unseen_events = get_unseen_events(local_ledger.event_log, remote_version_vector)
    remote_events = exchange_events(remote_node_id, local_unseen_events)
    
    if remote_events is None:
        # Event log compacted past divergence — fall back to full comparison
        remote_entries = exchange_full_ledger(remote_node_id)
        return reconcile_full_ledger(local_ledger, remote_entries, reconnection)
    
    # Step 4: Merge convergent types (SET_LIKE, COUNTER, OBSERVATIONAL)
    entries_merged = 0
    for event in remote_events:
        if event.semantic_type in (SET_LIKE, COUNTER, OBSERVATIONAL):
            _, changed = local_ledger.write_received(
                key=event.key, value=event.new_value,
                semantic_type=event.semantic_type,
                source_node=event.source_node,
                source_clock=event.lamport_clock,
                source_wall_time=event.wall_time,
                confidence=1.0,  # from peer, not relayed
                provenance=Provenance(origin=event.source_node, observation_type=DIRECT, hops=0)
            )
            if changed:
                entries_merged += 1
    
    # Step 5: Detect conflicts
    conflicts = detect_conflicts(local_ledger, local_events, remote_events)
    
    # Step 6: Resolve conflicts deterministically
    for conflict in conflicts:
        if conflict.semantic_type == EXCLUSIVE_OWNERSHIP:
            conflict.resolution = resolve_exclusive_ownership(conflict)
        elif conflict.semantic_type == RESOURCE:
            conflict.resolution = resolve_resource(conflict)
        elif conflict.semantic_type == MISSION_POLICY:
            conflict.resolution = resolve_mission_policy(conflict)
        
        # Apply resolution to local ledger
        local_ledger.write_local(
            key=conflict.key,
            value=conflict.resolution.winning_value,
            semantic_type=conflict.semantic_type
        )
        entries_merged += 1
    
    # Step 7: Build trace
    trace = ReconciliationTrace(
        reconnection=reconnection,
        divergence=divergence,
        conflicts_found=len(conflicts),
        conflicts_resolved=len([c for c in conflicts if c.resolution]),
        resolution_details=conflicts,
        entries_merged=entries_merged,
        duration_ms=(local_wall_time() - reconnection.detection_time) * 1000
    )
    
    # Step 8: Broadcast to sub-swarm
    broadcast_reconciliation(trace, reachable_neighbors)
    
    # Step 9: Execute side effects
    for conflict in conflicts:
        if conflict.resolution and conflict.resolution.side_effects:
            for effect in conflict.resolution.side_effects:
                execute_side_effect(effect)
    
    # Step 10: Re-evaluate degradation
    # The merged swarm may enable higher tiers
    trigger_degradation_re_evaluation(merged_swarm_state)
    
    return trace


def reconcile_full_ledger(local_ledger, remote_entries, reconnection):
    """
    Fallback: when event logs are unavailable, compare full ledgers.
    Less efficient but always works.
    """
    conflicts = []
    entries_merged = 0
    
    for key, remote_entry in remote_entries.items():
        local_entry = local_ledger.entries.get(key, None)
        
        if local_entry is None:
            # We don't have this key — accept remote
            local_ledger.entries[key] = remote_entry
            entries_merged += 1
            continue
        
        # Apply semantic merge
        if remote_entry.semantic_type in (SET_LIKE, COUNTER, OBSERVATIONAL):
            _, changed = local_ledger.write_received(
                key=key, value=remote_entry.value, ...
            )
            if changed:
                entries_merged += 1
        elif remote_entry.value != local_entry.value:
            conflicts.append(Conflict(
                key=key, local_entry=local_entry,
                remote_entry=remote_entry,
                semantic_type=local_entry.semantic_type
            ))
    
    # Also check: keys we have that remote doesn't
    for key, local_entry in local_ledger.entries.items():
        if key not in remote_entries:
            # Remote doesn't have this — they'll receive it when we broadcast
            pass
    
    # Resolve conflicts (same as event-based path)
    for conflict in conflicts:
        conflict.resolution = resolve_by_type(conflict)
        local_ledger.write_local(conflict.key, conflict.resolution.winning_value, ...)
        entries_merged += 1
    
    return ReconciliationTrace(
        reconnection=reconnection,
        divergence=DivergencePoint(clock_value=0, ...),  # full comparison
        conflicts_found=len(conflicts),
        conflicts_resolved=len(conflicts),
        resolution_details=conflicts,
        entries_merged=entries_merged
    )
```

---

## 10. WORKED EXAMPLE

### Scenario: Three-conflict reconciliation

**Setup:** Swarm of 6 nodes splits into two partitions:

- **Partition Alpha:** Nodes {1, 2, 3}
- **Partition Beta:** Nodes {4, 5, 6}
- **Partition duration:** ~120 seconds

**Pre-partition shared state:**
```
visited_zones = {zone_a}                    (SET_LIKE, clock=7)
task_owner.mapping_x = node_1               (EXCLUSIVE_OWNERSHIP, clock=8)
node_6.status = ACTIVE                      (RESOURCE, clock=6)
tasks_completed = 5                         (COUNTER, clock=7)
```

**During partition — Alpha's changes:**

| Event | Key | Value | Clock | Wall time |
|-------|-----|-------|-------|-----------|
| Node 1 visits zone_b | visited_zones | {zone_a, zone_b} | 9 | T+10 |
| Node 3 reassigned mapping | task_owner.mapping_x | node_3 | 12 | T+35 |
| Node 1 cannot reach node_6 | node_6.status | SUSPECTED_UNREACHABLE | 10 | T+20 |
| Alpha completes 2 tasks | tasks_completed | 7 | 11 | T+30 |

Alpha's final state:
```
visited_zones = {zone_a, zone_b}            (SET_LIKE, clock=11)
task_owner.mapping_x = node_3               (EXCLUSIVE_OWNERSHIP, clock=12)
node_6.status = SUSPECTED_UNREACHABLE       (RESOURCE, clock=10, wall_time=T+20)
tasks_completed = 7                         (COUNTER, clock=11)
```
Node 3 has mapping_x at **60% progress**, match_quality=0.75.

**During partition — Beta's changes:**

| Event | Key | Value | Clock | Wall time |
|-------|-----|-------|-------|-----------|
| Node 5 visits zone_c, zone_d | visited_zones | {zone_a, zone_c, zone_d} | 13 | T+45 |
| Node 5 assigned mapping (after timeout) | task_owner.mapping_x | node_5 | 14 | T+50 |
| Node 6 sends heartbeat | node_6.status | ACTIVE | 15 | T+60 |
| Beta completes 3 tasks | tasks_completed | 8 | 16 | T+70 |

Beta's final state:
```
visited_zones = {zone_a, zone_c, zone_d}    (SET_LIKE, clock=13)
task_owner.mapping_x = node_5               (EXCLUSIVE_OWNERSHIP, clock=14)
node_6.status = ACTIVE                      (RESOURCE, clock=15, wall_time=T+60)
tasks_completed = 8                         (COUNTER, clock=16)
```
Node 5 has mapping_x at **30% progress**, match_quality=0.82.

---

### Reconnection: Node 2 (Alpha) ↔ Node 4 (Beta)

**Step 1: Exchange summaries.**

Node 2 (Alpha) clock = 12, Node 4 (Beta) clock = 16.
Summary exchange → last common event at clock=8 (pre-partition shared state).

DivergencePoint: clock=8, local_events_since=4, remote_events_since=4.

**Step 2: Exchange events since clock=8.**

Alpha sends: [{clock=9, visited_zones}, {clock=10, node_6.status}, {clock=11, tasks_completed}, {clock=12, task_owner.mapping_x}]

Beta sends: [{clock=13, visited_zones}, {clock=14, task_owner.mapping_x}, {clock=15, node_6.status}, {clock=16, tasks_completed}]

**Step 3: Merge convergent types.**

**visited_zones (SET_LIKE):**
- Alpha: {zone_a, zone_b}
- Beta: {zone_a, zone_c, zone_d}
- Union: **{zone_a, zone_b, zone_c, zone_d}**
- No conflict.  Both sides independently arrive at the same union.

**tasks_completed (COUNTER):**
- Alpha: 7
- Beta: 8
- Max: **8**
- No conflict.

**Step 4: Detect conflicts.**

Keys modified on both sides: visited_zones (SET_LIKE, no conflict), task_owner.mapping_x (EXCLUSIVE_OWNERSHIP), node_6.status (RESOURCE), tasks_completed (COUNTER, no conflict).

Conflicts:
1. **task_owner.mapping_x** — Alpha says node_3 (clock=12), Beta says node_5 (clock=14)
2. **node_6.status** — Alpha says SUSPECTED_UNREACHABLE (clock=10, T+20), Beta says ACTIVE (clock=15, T+60)

**Step 5: Resolve conflicts.**

---

**Conflict 1: task_owner.mapping_x (EXCLUSIVE_OWNERSHIP)**

```
Local (Alpha):  node_3, clock=12, wall_time=T+35
Remote (Beta):  node_5, clock=14, wall_time=T+50
```

Resolution cascade:
1. **Progress comparison:** node_3 = 60%, node_5 = 30%.  Difference = 30% > PROGRESS_EPSILON (5%).  **Node 3 wins (higher progress).**
2. Quality and tiebreak not needed.

```
Resolution:
  strategy:       EXCLUSIVE_OWNERSHIP_CASCADE
  winning_value:  node_3
  winning_source: Alpha
  reason:         "Higher progress: node_3 at 60% vs node_5 at 30%"
  side_effects:   [RELEASE_EXECUTOR(node_5, mapping_x)]
```

Node 5 will be instructed to stop executing mapping_x and release its resources.

> **Note:** Even though Beta's clock (14) > Alpha's clock (12), Alpha's executor wins because progress is the primary tiebreaker — not clock value.  This is why HESK does not use "latest wins."

---

**Conflict 2: node_6.status (RESOURCE)**

```
Local (Alpha):  SUSPECTED_UNREACHABLE, clock=10, wall_time=T+20
Remote (Beta):  ACTIVE, clock=15, wall_time=T+60
```

Drift-guarded recency:
- time_diff = (T+60) - (T+20) = 40 seconds
- 40 > Δ_max (2.0)? **YES** → remote is clearly more recent

But also: Beta's observation is DIRECT (node_6 sent a heartbeat to Beta).  Alpha's is INFERRED (heartbeat timeout).  Even without recency, DIRECT trumps INFERRED.

```
Resolution:
  strategy:       RESOURCE_RECENCY
  winning_value:  ACTIVE
  winning_source: Beta
  reason:         "Remote observation is 40.0s newer AND DIRECT observation vs INFERRED"
```

This resolves correctly: node_6 IS active — it was just in Beta's partition, unreachable from Alpha.  Alpha's belief was wrong but reasonable given its local information (Invariant 7: communication failure ≠ death).

---

**Step 6: Apply resolutions.**

Both Node 2 and Node 4 compute the SAME resolutions independently (deterministic rules, same inputs).

Post-reconciliation state (on both sides):
```
visited_zones = {zone_a, zone_b, zone_c, zone_d}   ← UNION
task_owner.mapping_x = node_3                        ← progress wins
node_6.status = ACTIVE                               ← more recent direct observation
tasks_completed = 8                                  ← MAX
```

**Step 7: Broadcast.**

Node 2 broadcasts to Nodes 1, 3 (Alpha sub-swarm).
Node 4 broadcasts to Nodes 5, 6 (Beta sub-swarm).

All 6 nodes converge on the same state.

**Step 8: Side effects.**

- Node 5 receives RELEASE_EXECUTOR for mapping_x → stops mapping, frees resources.
- Node 5's freed resources may enable an upgrade for another degraded task.

**Step 9: Re-evaluate degradation.**

The merged swarm has 6 nodes instead of 3.  Tasks that were degraded due to insufficient resources may now be upgradeable.  Algorithm 006 runs an upgrade pass.

---

## 11. EDGE CASES

### E1: Three or more partitions reconnect simultaneously

Partitions Alpha, Beta, and Gamma all reconnect at roughly the same time.

**Handling:** Each pair reconciles independently: A↔B, A↔C, B↔C.  Because the resolution rules are deterministic and the merge operations for convergent types are commutative and associative, the order of pairwise reconciliation does not affect the final state.  All nodes converge regardless of which pairs reconcile first.

### E2: Cascading reconciliation

Partition Alpha reconnects with Beta.  During reconciliation, Alpha discovers that node_6 (which it thought was dead) is alive in Beta.  This changes Alpha's resource availability, triggering a degradation re-evaluation, which changes task assignments, which creates new ledger entries, which may conflict with Gamma's state if Gamma reconnects later.

**Handling:** Each reconciliation is a complete operation that updates the ledger and broadcasts results.  Subsequent reconciliations (with Gamma) will use the already-reconciled state.  The cascade is naturally ordered: first reconciliation updates state, second reconciliation compares against updated state.

### E3: Reconciliation during active task execution

Node 3 is actively executing mapping_x when reconciliation determines it should continue.  Node 5 is also actively executing mapping_x when reconciliation determines it should stop.

**Handling:** Node 5 receives a RELEASE_EXECUTOR side effect.  It should:
1. Complete any in-progress operation gracefully (don't corrupt data mid-write)
2. Save any useful partial results (the 30% work may have produced valid partial data)
3. Release resources
4. Transition the task to BIDDING state locally (task is now assigned to node_3 by reconciliation)

### E4: Both partitions abandoned the same task

Alpha determined mapping_x was unsatisfiable and abandoned it.  Beta also abandoned it.

**Handling:** No EXCLUSIVE_OWNERSHIP conflict (both values are ABANDONED or task_owner is cleared).  SET_LIKE/COUNTER entries merge normally.  The task remains abandoned.

However: the MERGED swarm (6 nodes instead of 3) might be able to satisfy the task.  The degradation re-evaluation in Step 9 should detect this and attempt to restart the abandoned task.

### E5: Event log compaction during partition

A partition lasts 15 minutes.  The event retention window is 10 minutes.  Events from the first 5 minutes of partition are lost.

**Handling:** Fall back to full ledger comparison (§9, `reconcile_full_ledger`).  This is less efficient but always correct.

### E6: Reconciliation discovers a "dead" node is alive

Alpha marked node_6 as FAILED_CONFIRMED (not just SUSPECTED_UNREACHABLE).  Beta shows node_6 was active the entire time.

**Handling:** RESOURCE resolution: Beta's ACTIVE observation is more recent AND direct.  Node_6 is marked ACTIVE.  However, any decisions Alpha made based on node_6's "death" (task reassignments, degradation) have already taken effect.  These are NOT automatically rolled back — they are valid decisions made with locally-available information at the time.  The re-evaluation pass may adjust assignments if node_6's return enables better allocation.

---

## 12. FAILURE MODES

### F1: Non-deterministic resolution

If the resolution algorithm uses any non-deterministic input (random tiebreak, local preference, wall-clock at resolution time), the two reconciling nodes will compute different results, creating NEW inconsistency.

**Mitigation:** The resolution algorithm is carefully designed to be deterministic.  All tiebreaks use immutable properties (node_id comparison).  No randomness is used.

### F2: Progress information unavailable

EXCLUSIVE_OWNERSHIP resolution requires task execution progress.  If progress tracking failed on one side, the primary tiebreaker is unavailable.

**Mitigation:** Default progress to 0.0 if unknown.  This effectively falls through to match_quality as the tiebreaker.  Log a warning.

### F3: Large event log exchange

After a long partition, the event exchange may involve thousands of events, consuming significant bandwidth.

**Mitigation:**
1. Use delta exchange (only events since divergence), not full log.
2. Compress events before transmission.
3. For very large exchanges, use a Merkle tree comparison to identify only the differing subtrees (§14 Q5).
4. If bandwidth is severely constrained, use SUMMARY mode (keys + clocks only) to identify conflicts, then exchange only conflicting entries.

### F4: Reconciliation message lost

Node A sends its event log to Node B, but the message is lost.  Node B cannot reconcile.

**Mitigation:** The reconciliation protocol should include acknowledgments and retries.  If the reconnection link is too unstable for reliable exchange, reconciliation is deferred until the link stabilizes.

---

## 13. INVARIANTS

**I1. Reconciliation is deterministic.**  Given the same local and remote state, any node computes the same resolutions.

**I2. SET_LIKE and COUNTER types always converge.**  Union and max are commutative, associative, and idempotent.

**I3. EXCLUSIVE_OWNERSHIP conflicts are explicitly resolved, never silently overwritten.**  Every conflict resolution has a reason string and a trace entry.

**I4. No node accesses global state during reconciliation.**  Resolutions are computed from the two reconciling nodes' ledgers and exchanged events only.

**I5. Post-reconciliation, both nodes agree on all resolved entries.**  This is guaranteed by determinism — both nodes process the same inputs through the same rules.

**I6. Reconciliation does not roll back valid decisions.**  Decisions made during the partition (task reassignments, degradation tier changes) are not automatically undone.  They are re-evaluated based on the merged state.

**I7. Partition reconnection triggers degradation re-evaluation.**  The merged swarm has more resources than either partition alone.  Tasks degraded due to resource scarcity should be considered for upgrade.

**I8. Every conflict resolution is logged.**  The ReconciliationTrace provides full explainability.

---

## 14. OPEN QUESTIONS

### Q1: Should reconciliation trigger automatic task upgrades?

**Question:** When partitions merge and the combined swarm has more resources, should reconciliation automatically attempt to upgrade degraded tasks to higher tiers?

**Options:**
- **Yes, automatic upgrade:** Reconciliation triggers 006's `attempt_upgrade()` for all currently-degraded tasks.
- **No, deferred upgrade:** Reconciliation only merges state.  Upgrades happen through normal 006 operation.

**Provisional v0.1 choice:** Yes, automatic trigger.  The merged swarm likely has capabilities that were unavailable to either partition alone.  Deferring upgrade means continuing to operate at unnecessarily degraded quality.

### Q2: What if both partitions abandoned the same task, but the merged swarm can satisfy it?

**Question:** Should reconciliation restart an abandoned task if the merged swarm has sufficient capability?

**Options:**
- **Yes:** Tasks in ABANDONED state are re-evaluated against the merged swarm's capabilities.
- **No:** Once abandoned, a task stays abandoned until explicitly restarted by a new trigger.

**Provisional v0.1 choice:** Yes, re-evaluate.  An abandoned CRITICAL task should be restarted if the merged swarm can satisfy it.  The re-evaluation uses the same logic as 006's upgrade pass.

### Q3: Eager vs. lazy reconciliation

**Question:** When should reconciliation happen — immediately upon reconnection, or lazily when a conflicting key is accessed?

**Options:**
- **Eager (v0.1):** Reconcile all state immediately upon reconnection.  Higher upfront cost but consistent state immediately.
- **Lazy:** Reconcile keys on-demand when accessed.  Lower upfront cost but risks operating on inconsistent state.

**Provisional v0.1 choice:** Eager.  In a real-time swarm, operating on inconsistent state (e.g., two nodes both believing they own the same task) causes immediate operational problems.  The cost of eager reconciliation is acceptable.

### Q4: How to handle very long partitions (hours/days)?

**Question:** If a partition lasts much longer than the event retention window, full ledger comparison may be expensive.  Should there be a mechanism for efficient long-partition reconciliation?

**Options:**
- **Full ledger comparison (v0.1):** Exchange all entries.  Simple, always correct.
- **Merkle tree comparison:** Build Merkle trees over ledger keys.  Exchange only differing subtrees.  Much more efficient for large ledgers with few differences.
- **Epoch-based checkpointing:** Periodically snapshot the ledger.  Exchange only changes since the most recent common checkpoint.

**Provisional v0.1 choice:** Full ledger comparison as fallback.  If performance testing shows this is too slow, implement Merkle trees in v0.2.

### Q5: Multi-party reconciliation protocol

**Question:** When 3+ partitions reconnect simultaneously, should there be a multi-party protocol instead of pairwise?

**Analysis:** Pairwise reconciliation with deterministic, commutative merge operations is sufficient for convergence — the order of pairwise reconciliation does not affect the final state for convergent types (SET_LIKE, COUNTER).  For EXCLUSIVE_OWNERSHIP, pairwise resolution produces a winner that is then used in subsequent pairwise reconciliations, which also produces a deterministic result.

**v0.1 approach:** Pairwise reconciliation only.  Correctness is guaranteed by commutativity of convergent types and determinism of conflict resolution.

### Q6: Transition period during reconciliation

**Question:** During the reconciliation exchange (which takes non-zero time), should the nodes pause normal operations to avoid creating new conflicts?

**Options:**
- **No pause (v0.1):** Continue normal operations during reconciliation.  New events may create additional conflicts that require another reconciliation pass.
- **Brief pause:** Pause task assignments (but not sensing/monitoring) during reconciliation.
- **Transactional:** Reconcile as an atomic operation.

**Provisional v0.1 choice:** No pause.  Pausing a real-time system during reconciliation risks missing critical events.  If reconciliation takes long enough that new conflicts arise, the normal merge rules handle them.

---

## 15. BASELINE FOR COMPARISON

### Baseline: Last-write-wins key-value store

Every state entry is a simple key-value pair.  On merge, the entry with the most recent wall-clock timestamp wins.

### Failure 1: Clock drift causes wrong ownership winner

```
Alpha: task_owner.mapping_x = node_3  at T+35  (Alpha's clock is 1s fast: reads T+36)
Beta:  task_owner.mapping_x = node_5  at T+50  (Beta's clock is accurate)

LWW: T+50 > T+36 → node_5 wins.

But node_3 has 60% progress, node_5 has 30% progress.
LWW discards 60% of completed work.

HESK: Progress-based resolution → node_3 wins, preserving work.
```

### Failure 2: SET_LIKE overwrite instead of union

```
Alpha: visited_zones = {zone_a, zone_b}  at T+10
Beta:  visited_zones = {zone_a, zone_c, zone_d}  at T+45

LWW: T+45 > T+10 → {zone_a, zone_c, zone_d}
zone_b is LOST.

HESK: Union → {zone_a, zone_b, zone_c, zone_d}
All exploration preserved.
```

### Failure 3: RESOURCE overwrite ignoring observation quality

```
Alpha: node_6.status = ACTIVE  (DIRECT heartbeat at T+5)
Beta:  node_6.status = SUSPECTED_UNREACHABLE  (INFERRED from timeout at T+8)

LWW: T+8 > T+5 → SUSPECTED_UNREACHABLE wins.
But the DIRECT observation is more trustworthy than the INFERENCE.

HESK: Drift-guarded comparison with provenance scoring.
If within drift margin: DIRECT (provenance 1.0) beats INFERRED (provenance 0.5).
```

### Comparison metrics

| Metric | LWW Baseline | HESK 008 |
|--------|-------------|----------|
| Set data preserved | WRONG (overwrite) | Correct (union) |
| Ownership resolved by progress | No (by timestamp) | Yes |
| Clock drift handled | No | Yes (drift guard) |
| Observation quality considered | No | Yes (provenance) |
| Work preservation | Poor (may discard progress) | Good (progress-aware) |
| Decision explainability | None | Full reconciliation trace |
| Multi-partition convergence | Not guaranteed | Guaranteed (deterministic + commutative) |
