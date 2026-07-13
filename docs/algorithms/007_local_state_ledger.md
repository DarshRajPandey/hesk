# 007 — Local State Ledger

> **Status:** v0.1 draft — distributed state foundation  
> **Depends on:** [001 Capability Model](./001_capability_model.md), [002 Task Model](./002_task_model.md)  
> **Consumed by:** [008 Partition Reconciliation](./008_partition_reconciliation.md), all algorithms (003–006) implicitly query the ledger  
> **Prior art:** Lamport clocks [Lamport, 1978], CRDTs [Shapiro et al., 2011], state-based convergence in distributed systems

---

## 1. PROBLEM

### 1.1 Core question

> How does each HESK node store, version, update, and query its local beliefs about the state of the world — including its own state, other nodes' states, task assignments, and swarm membership — such that these beliefs can be meaningfully exchanged, compared, and reconciled without requiring global consensus?

### 1.2 Why this matters

There is NO global state in HESK.  This is Architectural Invariant 1: no node may directly access simulation truth (or any centralized database).

Every node has a **partial, stale, potentially inconsistent** view of the swarm.  This is not a bug — it is the foundational design of any truly distributed system.  The local state ledger is the mechanism that gives structure to this partial view, enabling:

- **Algorithms 003–006** to query "what do I believe about node X?" and act on that belief
- **Algorithm 008** to identify conflicts when partitions reconnect and merge divergent beliefs
- **Decision tracing** to explain why a node made a particular decision ("I assigned mapping to B because I believed A was unreachable at clock=42")

### 1.3 Belief vs. fact

The ledger stores **beliefs**, not ground truth.

When the ledger contains `node_7.status = SUSPECTED_UNREACHABLE`, this means:
- This node has not received a heartbeat from node 7 for longer than `heartbeat_timeout_s`
- Node 7 may actually be alive and healthy in another partition (Invariant 7: communication failure ≠ death)
- Other nodes may hold a contradictory belief (node 4 may believe node 7 is ACTIVE)

The distinction between belief and fact is fundamental.  Every entry in the ledger is tagged with provenance — who said it, when, and how they know — so downstream algorithms and reconciliation can reason about the quality of each belief.

### 1.4 Why state semantic types are critical

Not all state is created equal.  Consider three ledger entries:

1. `visited_zones = {zone_a, zone_b}` — This is a SET.  When two nodes merge their visited_zones, the correct operation is UNION, not "latest wins."
2. `task_owner.mapping = node_7` — This is an EXCLUSIVE OWNERSHIP claim.  Only one node can own a task.  If two partitions assigned the same task to different nodes, this is a CONFLICT that requires resolution.
3. `node_9.battery = 0.42` — This is a RESOURCE observation.  The most recent direct observation is most likely to be accurate.

A key-value store with last-write-wins semantics would silently corrupt all three cases.  The local state ledger must be **semantics-aware**.

---

## 2. DEFINITIONS

### 2.1 Shared notation

| Symbol | Meaning |
|--------|---------|
| n_i | Node i |
| L_i | Local ledger of node i |
| λ_i | Lamport clock of node i |
| Δ_max | Maximum assumed wall-clock drift between nodes (seconds) |

### 2.2 State semantic types

The type of a state entry governs how it is updated on receive and how conflicts are resolved during reconciliation (008).

| Semantic type | Merge rule | Monotonic? | Conflict possible? | Examples |
|---------------|-----------|------------|-------------------|----------|
| SET_LIKE | Union | Yes (only grows) | No (union is commutative, associative, idempotent) | visited_zones, discovered_targets |
| VECTOR_COUNTER | Element-wise max | Yes (only increases) | No | tasks_completed, messages_sent |
| MONOTONIC_MEASUREMENT | Max | Yes (only increases) | No (max is commutative, associative, idempotent) | highest_altitude_reached |
| EXCLUSIVE_OWNERSHIP | Accept higher clock; flag conflict if concurrent | No | **YES** — the hard case | task_owner.{task_id}, coalition_coordinator |
| OBSERVATIONAL | Preserve both with provenance | No | Multiple values coexist (not a "conflict" in the ownership sense) | target_position, obstacle_location |
| RESOURCE | Most recent observation wins (with drift guard) | No | Rare (drift edge case) | node_X.battery_level, node_X.cpu_load |
| REACHABILITY | Observer-relative preservation | No | No (Stored as bipartite graph edges) | reachability.A_to_C |
| MISSION_POLICY | Higher authority wins | No | Possible if authorities diverge | priority_overrides, mission_parameters |

> **Relation to CRDTs [Shapiro et al., 2011]:**  SET_LIKE and VECTOR_COUNTER are essentially Grow-Only Set (G-Set) and G-Counter CRDTs respectively.  They are guaranteed to converge under any message ordering.  HESK acknowledges this prior art.  EXCLUSIVE_OWNERSHIP is NOT a CRDT — it requires application-level conflict resolution (handled by 008).

### 2.3 LedgerEntry

The fundamental unit of state:

```
LedgerEntry:
  key:              string              # hierarchical key, e.g., "task_owner.mapping_zone_b"
  value:            any                 # the belief (set, int, node_id, float, etc.)
  semantic_type:    StateSemanticType   # SET_LIKE | COUNTER | EXCLUSIVE_OWNERSHIP | ...
  source_node:      NodeId              # who originated this belief
  lamport_clock:    int                 # logical clock at time of writing
  wall_time:        float               # wall-clock timestamp (seconds since epoch)
  confidence:       float ∈ [0, 1]     # trust in this belief
  provenance:       Provenance          # how this belief was obtained
```

### 2.4 Provenance

```
Provenance:
  origin:           NodeId              # the node that first observed/created this fact
  observation_type: DIRECT | RELAYED | INFERRED
  relay_chain:      [NodeId]            # if RELAYED, the path the information took
  original_clock:   int                 # Lamport clock at the origin node when created
  hops:             int                 # number of relay hops (0 for DIRECT)
```

| Observation type | Meaning | Confidence modifier |
|-----------------|---------|-------------------|
| DIRECT | This node directly observed/decided this fact | 1.0 (highest trust) |
| RELAYED | Received from another node who received it from another | 0.8^hops (decays with relay chain length) |
| INFERRED | Derived from other state (e.g., inferred node death from heartbeat timeout) | 0.7 (lower trust, derived) |

### 2.5 Event

The event log records every state change for reconciliation (008):

```
Event:
  event_id:         string              # origin_node_id + origin_sequence_number
  type:             WRITE | UPDATE | DELETE
  key:              string              # which entry was affected
  semantic_type:    StateSemanticType   # the entry's semantic type
  old_value:        any or None         # previous value before this event (locally)
  new_value:        any                 # new value after this event
  lamport_clock:    int                 # local clock when this event was applied
  origin_node:      NodeId              # node that originally created this event
  origin_seq:       int                 # origin node's sequence number for this event
  wall_time:        float               # wall-clock timestamp when applied locally
```

### 2.6 Ledger

The top-level structure on each node:

```
Ledger:
  node_id:          NodeId              # this node's identity
  entries:          {string: LedgerEntry}  # key → entry mapping
  event_log:        [Event]             # append-only event history
  lamport_clock:    int                 # this node's current Lamport clock
```

### 2.7 Lamport clock rules [Lamport, 1978]

This is established prior art.  HESK uses standard Lamport clock semantics:

1. **Internal event:** Before any internal state change, increment: `λ_i = λ_i + 1`
2. **Send message:** Before sending, increment: `λ_i = λ_i + 1`.  Attach λ_i to the message.
3. **Receive message:** On receiving message with clock λ_msg: `λ_i = max(λ_i, λ_msg) + 1`

**What Lamport clocks provide:** Causal ordering.  If event A causally precedes event B (A → B), then clock(A) < clock(B).

**What Lamport clocks do NOT provide:** The converse.  clock(A) < clock(B) does NOT imply A → B.  Events may be concurrent (neither caused the other) but still have different clock values.  Lamport clocks cannot detect concurrency.

> **PROVISIONAL v0.1 CHOICE:** HESK v0.1 uses Lamport clocks despite this limitation.  The alternative — vector clocks — provides if-and-only-if concurrency detection but costs O(N) space per event (where N = number of nodes) and requires membership management.  For a dynamic swarm with nodes joining and leaving, vector clocks add significant complexity.
>
> **Known limitation:** Some EXCLUSIVE_OWNERSHIP conflicts will not be detected as concurrent by Lamport clocks alone.  Two updates with clock values 12 and 14 may be concurrent (from different partitions) but look sequential.  v0.1 mitigates this by also using wall_time with drift guard (§7.4).
>
> **Future upgrade path:** If experiments show that missed concurrency detection causes significant problems, upgrade to vector clocks or interval tree clocks [Almeida et al., 2008] in v0.2.

---

## 3. ASSUMPTIONS

**A1. Node identity is stable.**  Each node has a unique, persistent identifier that does not change across reboots.  Node IDs are established before mission start.

**A2. Wall-clock drift is bounded.**  The absolute wall-clock drift between any two nodes is ≤ Δ_max.  v0.1 default: Δ_max = 2.0 seconds.  This is reasonable for nodes with GPS time sync or NTP.

**A3. Event log is append-only.**  Events are never retroactively modified or deleted from the log.  They may be compacted (old events evicted) according to the retention policy, but this only removes events from the log — it does not rewrite history.

**A4. No Byzantine failures.**  Nodes do not deliberately lie about their state or forge events.  Failures are crash-stop or omission, not malicious.

**A5. Lamport clocks are sufficient for v0.1.**  As discussed in §2.7, this is a known limitation with a planned upgrade path.

**A6. Storage is finite but adequate.**  Each node has enough storage for the ledger entries and a bounded event log.  The event log is bounded by the retention policy (§7.6).

---

## 4. INPUTS

### For write_local (own observation)

| Input | Source | Description |
|-------|--------|-------------|
| key | Algorithm decision or sensor reading | The state entry to update |
| value | Computed or observed | The new value |
| semantic_type | Schema definition | The type of this entry (SET_LIKE, COUNTER, etc.) |

### For write_received (incoming state update)

| Input | Source | Description |
|-------|--------|-------------|
| key | Received message | The state entry being updated |
| value | Received message | The remote node's value for this entry |
| semantic_type | Received message | Type tag |
| source_node | Received message | Who sent this update |
| source_clock | Received message | Sender's Lamport clock at send time |
| source_wall_time | Received message | Sender's wall time at send time |
| confidence | Received message | Sender's confidence in this value |
| provenance | Received message | How the sender obtained this value |

### For read

| Input | Source | Description |
|-------|--------|-------------|
| key | Calling algorithm | Which entry to query |

---

## 5. LOCALLY AVAILABLE INFORMATION

### KNOWN LOCALLY
- This node's entire ledger L_i (all entries, all events)
- This node's Lamport clock λ_i
- This node's wall clock
- This node's event log (complete up to retention boundary)
- Which entries were written locally vs. received

### RECEIVED VIA MESSAGES
- State updates from other nodes, carried in periodic state-exchange messages or piggybacked on heartbeats
- Each received update carries: key, value, semantic_type, source_node, source_clock, source_wall_time, confidence, provenance

### INFERRED
- Relative ordering of events (from Lamport clock comparisons)
- Node reachability (presence/absence of heartbeats — stored as RESOURCE-type entries)
- Freshness of each entry (wall_time age)

### UNKNOWN
- Events that occurred on unreachable nodes (these nodes may have written to THEIR ledgers but we have no knowledge of it)
- Whether two events with different Lamport clock values are causally ordered or concurrent (Lamport limitation)
- The true current state of any remote node (we have only its last reported state, subject to staleness)

---

## 6. OUTPUT

### From write_local

Returns the created `LedgerEntry` with updated Lamport clock.

### From write_received

Returns the resulting `LedgerEntry` after semantic merge, plus a flag indicating whether the local value was changed.

### From read

Returns `(value, metadata)` where metadata includes: semantic_type, source_node, lamport_clock, wall_time, confidence, provenance.

### From get_events_since

Returns `[Event]` — all events in the event log with lamport_clock > the given clock value.  Used by Algorithm 008 during reconciliation.

---

## 7. DECISION RULE

### 7.1 write_local: own observation

When this node makes a local observation or decision:

1. Increment Lamport clock: `λ_i = λ_i + 1`
2. Create new LedgerEntry with:
   - source_node = self
   - lamport_clock = λ_i
   - wall_time = local wall clock
   - confidence = 1.0
   - provenance = {origin: self, observation_type: DIRECT, hops: 0}
3. Store entry in ledger at key
4. Append WRITE or UPDATE Event to event log

### 7.2 write_received: incoming state update

When this node receives a state update from another node:

1. Update Lamport clock: `λ_i = max(λ_i, source_clock) + 1`
2. Look up existing entry for this key in local ledger.
3. Apply **semantic merge** based on the entry's semantic_type:

#### Semantic merge rules

| Type | Rule | Result |
|------|------|--------|
| **SET_LIKE** | Union local and received values | `entry.value = entry.value ∪ received_value` |
| **COUNTER** | Take maximum | `entry.value = max(entry.value, received_value)` |
| **EXCLUSIVE_OWNERSHIP** | If received_clock > local_clock: accept. If local_clock > received_clock: keep. If approximately concurrent (see §7.4): flag CONFLICT. | Accept or keep or conflict |
| **OBSERVATIONAL** | Store both values with their provenances. If storage is full, evict lowest-confidence observation. | Multiple observations coexist |
| **RESOURCE** | If received is more recent (wall_time, with drift guard): accept. Otherwise: keep. | Most recent wins |
| **MISSION_POLICY** | If received has higher authority: accept. Otherwise: keep. | Authority-based |

4. Update provenance (increment hops if relayed)
5. Append UPDATE Event to event log

### 7.3 SET_LIKE and COUNTER: convergence guarantee

Because SET_LIKE uses union and COUNTER uses max, these operations are:
- **Commutative:** A ∪ B = B ∪ A, max(A, B) = max(B, A)
- **Associative:** (A ∪ B) ∪ C = A ∪ (B ∪ C)
- **Idempotent:** A ∪ A = A, max(A, A) = A

This guarantees convergence: regardless of message ordering, all nodes that receive the same set of updates will arrive at the same value.  This is the CRDT property [Shapiro et al., 2011].

### 7.4 EXCLUSIVE_OWNERSHIP: concurrency detection with Lamport clocks

This is the hardest case.  Two partitions may independently assign the same task to different nodes.

v0.1 heuristic for detecting potentially concurrent updates:

```
def is_potentially_concurrent(local_entry, received):
    clock_diff = abs(local_entry.lamport_clock - received.source_clock)
    wall_diff = abs(local_entry.wall_time - received.source_wall_time)
    
    # If clocks are close AND wall times are close, treat as potentially concurrent
    if clock_diff <= CONCURRENCY_CLOCK_THRESHOLD and wall_diff <= Δ_max + CONCURRENCY_WALL_THRESHOLD:
        return True
    
    # If wall times suggest the events could have been concurrent despite clock ordering
    if wall_diff <= Δ_max + CONCURRENCY_WALL_THRESHOLD:
        return True
    
    return False
```

v0.1 defaults:
- `CONCURRENCY_CLOCK_THRESHOLD = 5` (events within 5 Lamport ticks)
- `CONCURRENCY_WALL_THRESHOLD = 3.0` seconds

When an EXCLUSIVE_OWNERSHIP update is determined to be concurrent:
1. **Do NOT silently overwrite.**
2. Flag the entry as CONFLICTED.
3. Store BOTH values (local and received) with their provenances.
4. The conflict is resolved by Algorithm 008 (partition reconciliation) or by a deterministic resolution rule if immediate resolution is needed.

### 7.5 RESOURCE: drift-guarded recency

For RESOURCE-type entries (e.g., node_X.battery_level), the most recent observation is generally most accurate.  But wall-clock drift can cause incorrect ordering.

```
def accept_resource_update(local_entry, received):
    time_diff = received.source_wall_time - local_entry.wall_time
    
    # Accept only if received is meaningfully newer (beyond drift margin)
    if time_diff > Δ_max:
        return True  # clearly newer
    elif time_diff < -Δ_max:
        return False  # clearly older
    else:
        # Within drift margin — ambiguous
        # Tiebreak: prefer DIRECT over RELAYED, then higher confidence
        if received.provenance.observation_type == DIRECT and local_entry.provenance.observation_type != DIRECT:
            return True
        elif received.confidence > local_entry.confidence:
            return True
        return False
```

### 7.6 Event log retention policy

The event log cannot grow unboundedly.  v0.1 retention policy:

```
retain(event) IF:
  event.lamport_clock > (current_clock - MAX_CLOCK_AGE)    # keep recent events
  OR event.wall_time > (now - MAX_WALL_AGE_S)              # keep events within time window
```

v0.1 defaults:
- `MAX_CLOCK_AGE = 1000` events
- `MAX_WALL_AGE_S = 600` seconds (10 minutes)

Events beyond both thresholds are eligible for compaction:

```
def compact_log(event_log, retention_policy):
    """Remove events that are beyond the retention window."""
    retained = [e for e in event_log if retention_policy.retain(e)]
    removed_count = len(event_log) - len(retained)
    event_log = retained
    return removed_count
```

Compaction is safe because:
1. The current ledger entries already reflect all applied events.
2. Compacted events are no longer needed for normal operation.
3. However, if a long-partitioned node reconnects and needs events older than the retention window, reconciliation (008) falls back to a full ledger comparison rather than log replay.

### 7.7 Serialization for network exchange

When exchanging state with another node (periodic sync or on-demand for reconciliation):

```
StateExchangeMessage:
  sender_id:        NodeId
  sender_clock:     int              # sender's Lamport clock
  version_vector:   {NodeId: int}    # sender's knowledge frontier
  entries:          [LedgerEntry]    # entries to share
  bandwidth_mode:   FULL | DELTA | SUMMARY
```

Bandwidth modes:
- **FULL:** Send all entries.  Used on first contact or after long partition.
- **DELTA:** Send only entries where `entry.origin_seq > peer_version_vector[entry.origin_node]`. Standard mode. A scalar Lamport clock cannot correctly identify unseen events.
- **SUMMARY:** Send version vectors and bloom filters of recent events to identify divergence.

---

## 8. PLAIN-ENGLISH ALGORITHM

### Local observation

1. Something happens locally (sensor reading, algorithm decision, heartbeat timeout).
2. Increment Lamport clock.
3. Create a LedgerEntry with the observation, tagged DIRECT, confidence 1.0.
4. Store in ledger, append event to log.

### Receiving remote state

1. A message arrives from node n_k containing state updates.
2. Update Lamport clock: `max(local, received) + 1`.
3. For each entry in the message:
   a. Look up the local entry for the same key.
   b. If no local entry exists → create one from the received data (with received provenance).
   c. If a local entry exists → apply the semantic merge rule for this entry's type.
   d. Append an event to the log recording what changed.

### Querying state

1. An algorithm (003, 004, 005, 006) calls `read(key)`.
2. The ledger returns the current value along with metadata (source, clock, confidence, provenance).
3. The calling algorithm uses the metadata to assess reliability (e.g., staleness-based confidence decay in 003).

### Preparing for reconciliation

1. Node X (re)connects to node Y.
2. They exchange Lamport clock values to find the divergence point.
3. Each node calls `get_events_since(divergence_clock)` to retrieve events the other hasn't seen.
4. These events are exchanged and processed through the semantic merge rules.
5. This is the handoff to Algorithm 008.

---

## 9. PSEUDOCODE

```python
class LocalStateLedger:
    def __init__(self, node_id):
        self.node_id = node_id
        self.entries = {}           # key → LedgerEntry
        self.event_log = []         # append-only events
        self.lamport_clock = 0
        self.seq_num = 0            # Origin sequence number for events
        self.version_vector = {node_id: 0} # Knowledge frontier
    
    def write_local(self, key, value, semantic_type):
        """Record a local observation or decision."""
        self.lamport_clock += 1
        self.seq_num += 1
        self.version_vector[self.node_id] = self.seq_num
        
        old_value = self.entries.get(key, None)
        
        entry = LedgerEntry(
            key=key,
            value=value,
            semantic_type=semantic_type,
            source_node=self.node_id,
            lamport_clock=self.lamport_clock,
            wall_time=local_wall_time(),
            confidence=1.0,
            provenance=Provenance(
                origin=self.node_id,
                observation_type=DIRECT,
                relay_chain=[],
                original_clock=self.lamport_clock,
                hops=0
            )
        )
        
        self.entries[key] = entry
        
        self.event_log.append(Event(
            event_id=f"{self.node_id}_{self.seq_num}",
            type=UPDATE if old_value else WRITE,
            key=key,
            semantic_type=semantic_type,
            old_value=old_value.value if old_value else None,
            new_value=value,
            lamport_clock=self.lamport_clock,
            origin_node=self.node_id,
            origin_seq=self.seq_num,
            wall_time=local_wall_time()
        ))
        
        return entry
    
    def write_received(self, key, value, semantic_type, source_node,
                       source_clock, source_wall_time, confidence, provenance):
        """Process a state update received from another node."""
        # Update Lamport clock
        self.lamport_clock = max(self.lamport_clock, source_clock) + 1
        
        local_entry = self.entries.get(key, None)
        
        if local_entry is None:
            # No local entry — accept the received value
            new_entry = LedgerEntry(
                key=key, value=value, semantic_type=semantic_type,
                source_node=source_node, lamport_clock=self.lamport_clock,
                wall_time=source_wall_time, confidence=confidence,
                provenance=provenance
            )
            self.entries[key] = new_entry
            self._append_event(WRITE, key, semantic_type, None, value)
            return new_entry, True  # changed = True
        
        # Apply semantic merge
        merged_value, changed, conflict = self._semantic_merge(
            local_entry, value, source_node, source_clock, 
            source_wall_time, confidence, provenance
        )
        
        if changed:
            local_entry.value = merged_value
            local_entry.lamport_clock = self.lamport_clock
            local_entry.wall_time = max(local_entry.wall_time, source_wall_time)
            local_entry.source_node = source_node
            local_entry.confidence = confidence
            local_entry.provenance = provenance
            self._append_event(UPDATE, key, semantic_type, local_entry.value, merged_value)
        
        if conflict:
            local_entry.conflict = ConflictRecord(
                local_value=local_entry.value,
                remote_value=value,
                remote_source=source_node,
                remote_clock=source_clock,
                detected_at=self.lamport_clock
            )
        
        return local_entry, changed
    
    def _semantic_merge(self, local_entry, received_value, source_node,
                        source_clock, source_wall_time, confidence, provenance):
        """Apply type-specific merge rules. Returns (merged_value, changed, conflict)."""
        
        stype = local_entry.semantic_type
        
        if stype == SET_LIKE:
            merged = local_entry.value | received_value  # set union
            changed = merged != local_entry.value
            return merged, changed, False
        
        elif stype == COUNTER:
            merged = max(local_entry.value, received_value)
            changed = merged != local_entry.value
            return merged, changed, False
        
        elif stype == EXCLUSIVE_OWNERSHIP:
            if source_clock > local_entry.lamport_clock:
                # Received is newer — accept
                return received_value, True, False
            elif source_clock < local_entry.lamport_clock:
                # Local is newer — keep
                return local_entry.value, False, False
            else:
                # Potentially concurrent — check heuristic
                if is_potentially_concurrent(local_entry, source_clock, source_wall_time):
                    # CONFLICT: do not overwrite, flag for resolution
                    return local_entry.value, False, True
                else:
                    # Same clock but not concurrent (unlikely) — tiebreak by node_id
                    if source_node < local_entry.source_node:
                        return received_value, True, False
                    return local_entry.value, False, False
        
        elif stype == OBSERVATIONAL:
            # Store both observations
            if not isinstance(local_entry.value, list):
                local_entry.value = [
                    Observation(value=local_entry.value, provenance=local_entry.provenance)
                ]
            local_entry.value.append(
                Observation(value=received_value, provenance=provenance)
            )
            # Evict if too many observations (keep most recent N)
            if len(local_entry.value) > MAX_OBSERVATIONS_PER_KEY:
                local_entry.value.sort(key=lambda o: o.provenance.original_clock, reverse=True)
                local_entry.value = local_entry.value[:MAX_OBSERVATIONS_PER_KEY]
            return local_entry.value, True, False
        
        elif stype == RESOURCE:
            if accept_resource_update(local_entry, source_wall_time, confidence, provenance):
                return received_value, True, False
            return local_entry.value, False, False
        
        elif stype == MISSION_POLICY:
            # Higher authority wins (lower authority_level number = higher authority)
            if provenance.authority_level < local_entry.provenance.authority_level:
                return received_value, True, False
            return local_entry.value, False, False
    
    def read(self, key):
        """Query a ledger entry."""
        entry = self.entries.get(key, None)
        if entry is None:
            return None, None
        return entry.value, {
            'semantic_type': entry.semantic_type,
            'source_node': entry.source_node,
            'lamport_clock': entry.lamport_clock,
            'wall_time': entry.wall_time,
            'confidence': entry.confidence,
            'provenance': entry.provenance,
            'has_conflict': hasattr(entry, 'conflict') and entry.conflict is not None
        }
    
    def get_events_since(self, clock_value):
        """Return all events with lamport_clock > clock_value.
        Used by Algorithm 008 for reconciliation."""
        return [e for e in self.event_log if e.lamport_clock > clock_value]
    
    def compact_log(self):
        """Remove events beyond the retention window."""
        now = local_wall_time()
        retained = [
            e for e in self.event_log
            if e.lamport_clock > (self.lamport_clock - MAX_CLOCK_AGE)
            or e.wall_time > (now - MAX_WALL_AGE_S)
        ]
        removed = len(self.event_log) - len(retained)
        self.event_log = retained
        return removed
    
    def _append_event(self, event_type, key, semantic_type, old_value, new_value):
        """Append an event to the log."""
        self.event_log.append(Event(
            event_id=f"{self.node_id}_{self.lamport_clock}",
            type=event_type,
            key=key,
            semantic_type=semantic_type,
            old_value=old_value,
            new_value=new_value,
            lamport_clock=self.lamport_clock,
            source_node=self.node_id,
            wall_time=local_wall_time()
        ))
```

---

## 10. WORKED EXAMPLE

### Scenario: Node A receives state update from Node B

**Node A's initial ledger state:**

```
KEY: visited_zones
  value:         {zone_1, zone_2}
  semantic_type: SET_LIKE
  source_node:   node_A
  lamport_clock: 5
  wall_time:     1000.0
  confidence:    1.0
  provenance:    DIRECT

KEY: task_owner.mapping_x
  value:         node_7
  semantic_type: EXCLUSIVE_OWNERSHIP
  source_node:   node_A
  lamport_clock: 3
  wall_time:     998.0
  confidence:    1.0
  provenance:    DIRECT

KEY: node_9.status
  value:         ACTIVE
  semantic_type: RESOURCE
  source_node:   node_9
  lamport_clock: 4
  wall_time:     999.5
  confidence:    0.9
  provenance:    DIRECT (heartbeat from node_9)
```

Node A's Lamport clock: λ_A = 5

**Node B sends state update containing:**

```
source_clock: 7

ENTRY 1:
  key:           visited_zones
  value:         {zone_2, zone_3}
  semantic_type: SET_LIKE
  source_clock:  7
  wall_time:     1002.0

ENTRY 2:
  key:           task_owner.mapping_x
  value:         node_8
  semantic_type: EXCLUSIVE_OWNERSHIP
  source_clock:  6
  wall_time:     1001.0

ENTRY 3:
  key:           node_9.status
  value:         SUSPECTED_UNREACHABLE
  semantic_type: RESOURCE
  source_clock:  8
  wall_time:     1003.0
```

**Processing step by step:**

**Update A's Lamport clock:** λ_A = max(5, 7) + 1 = **8**

---

**Entry 1: visited_zones (SET_LIKE)**

| | Local | Received |
|---|---|---|
| Value | {zone_1, zone_2} | {zone_2, zone_3} |
| Clock | 5 | 7 |

Merge rule: **UNION**

Result: `{zone_1, zone_2} ∪ {zone_2, zone_3}` = **{zone_1, zone_2, zone_3}**

Changed: YES (zone_3 added)

Event logged:
```
Event: UPDATE, key=visited_zones, old={zone_1,zone_2}, new={zone_1,zone_2,zone_3}, clock=8
```

> Note: This is guaranteed convergent.  If Node C also had {zone_4} and sent it to A and B independently, all three would eventually converge on {zone_1, zone_2, zone_3, zone_4} regardless of message order.

---

**Entry 2: task_owner.mapping_x (EXCLUSIVE_OWNERSHIP)**

| | Local | Received |
|---|---|---|
| Value | node_7 | node_8 |
| Clock | 3 | 6 |
| Wall time | 998.0 | 1001.0 |

Received clock (6) > local clock (3).  Clock difference = 3.  Wall time difference = 3.0s.

Concurrency check:
- clock_diff = 3 ≤ CONCURRENCY_CLOCK_THRESHOLD (5)? YES
- wall_diff = 3.0 ≤ Δ_max + CONCURRENCY_WALL_THRESHOLD (2.0 + 3.0 = 5.0)? YES
- Potentially concurrent? **YES**

> **Key Lamport limitation:** Clock 6 > Clock 3, so a naive system would accept node_8 as the "newer" owner.  But these events could have occurred in different partitions where node_A assigned node_7 and node_B independently assigned node_8.  The wall times are close enough that they COULD be concurrent despite the clock ordering.

Result: **CONFLICT flagged.**  Local value kept (node_7).  Both values stored in conflict record.

```
entry.conflict = ConflictRecord(
  local_value=node_7,    remote_value=node_8,
  remote_source=node_B,  remote_clock=6,
  detected_at=8
)
```

This conflict will be resolved by Algorithm 008 using task progress comparison.

Event logged:
```
Event: CONFLICT_DETECTED, key=task_owner.mapping_x, local=node_7, remote=node_8, clock=8
```

---

**Entry 3: node_9.status (RESOURCE)**

| | Local | Received |
|---|---|---|
| Value | ACTIVE | SUSPECTED_UNREACHABLE |
| Clock | 4 | 8 |
| Wall time | 999.5 | 1003.0 |

Drift-guarded recency check:
- time_diff = 1003.0 - 999.5 = 3.5s
- 3.5 > Δ_max (2.0)? **YES** → clearly newer

Result: **Accept received value.**  node_9.status = SUSPECTED_UNREACHABLE

Event logged:
```
Event: UPDATE, key=node_9.status, old=ACTIVE, new=SUSPECTED_UNREACHABLE, clock=8
```

---

**Node A's final ledger state:**

```
KEY: visited_zones
  value:         {zone_1, zone_2, zone_3}    ← UNION applied
  lamport_clock: 8

KEY: task_owner.mapping_x
  value:         node_7                       ← KEPT (conflict flagged)
  conflict:      {local: node_7, remote: node_8}
  lamport_clock: 8

KEY: node_9.status
  value:         SUSPECTED_UNREACHABLE        ← ACCEPTED (more recent)
  lamport_clock: 8
```

λ_A = 8.  Event log has 3 new entries.

---

## 11. EDGE CASES

### E1: Receiving an update for a key with unknown semantic type

A message contains a key that the receiving node has never seen with a semantic type not yet registered.

**Handling:** Accept the entry as-is, storing the value and semantic type.  The semantic type is carried IN the message — the receiving node does not need prior knowledge of it.

### E2: Stale Lamport clock after node reboot

A node reboots and loses its Lamport clock state.  It restarts at λ = 0, which is lower than all existing events.

**Handling:** On boot, the node should persist its last Lamport clock value to durable storage.  On reboot, it initializes from the persisted value.  If the persisted value is also lost, the node's first message exchange will update its clock to `max(0, received_clock) + 1`, rapidly catching up.  However, events generated between reboot and first message exchange will have artificially low clock values.

**Mitigation:** Store Lamport clock in persistent storage, write periodically (e.g., every 100 ticks).

### E3: Event log too large for reconciliation

A long partition results in thousands of events.  The event log has been compacted, and events before the divergence point are lost.

**Handling:** Algorithm 008 falls back to full ledger comparison: both nodes exchange their entire entry set (not the event log) and apply semantic merge rules to each key.  This is more expensive but does not require historical events.

### E4: SET_LIKE entry grows unboundedly

`visited_zones` accumulates zones forever (monotonic growth).

**Handling:** v0.1 does not cap SET_LIKE entries.  If zone sets become impractically large, a future version could introduce a "windowed set" that retains only recently-added elements.  This would sacrifice the CRDT convergence guarantee and is deferred.

### E5: OBSERVATIONAL entry with many conflicting observations

Multiple nodes report different `target_position` values for the same target.  All are stored.

**Handling:** v0.1 stores up to MAX_OBSERVATIONS_PER_KEY (default: 5) per OBSERVATIONAL entry, keeping the most recent by clock value.  Downstream algorithms must handle multi-valued entries (e.g., by taking the highest-confidence value or averaging).

### E6: Node receives its own old state relayed back

Node A wrote key X at clock 10.  The value was relayed through B → C → A at clock 15.  Node A receives "its own" observation relayed back with additional latency.

**Handling:** The semantic merge rules handle this correctly:
- SET_LIKE: union is idempotent (A's own zones are already in its set)
- COUNTER: max is idempotent
- RESOURCE: A's local entry is at clock 10 with wall_time T.  The relayed version has wall_time T (the original observation time, not the relay time).  Drift guard: time_diff = 0, which is within Δ_max → ambiguous tiebreak → DIRECT beats RELAYED → local kept.

---

## 12. FAILURE MODES

### F1: Clock drift exceeds Δ_max

If actual drift exceeds the assumed Δ_max, RESOURCE updates may be accepted incorrectly (an older observation appears newer due to clock skew).

**Mitigation:** Use GPS time sync where available.  If GPS is lost, increase Δ_max conservatively.  Log suspected drift anomalies.

### F2: Event log compaction loses reconciliation data

If a partition lasts longer than the retention window, events from before the partition are lost, and fine-grained reconciliation (008 event replay) is impossible.

**Mitigation:** Fall back to full ledger comparison.  Additionally, critical state types (EXCLUSIVE_OWNERSHIP) could have longer retention windows.

### F3: Silent overwrite on EXCLUSIVE_OWNERSHIP with clock ordering

Lamport clocks show clock(remote) > clock(local), suggesting remote is "newer."  But the events were concurrent (from different partitions).  The heuristic concurrency detection (§7.4) has thresholds that may miss some concurrent events.

**Mitigation:** The thresholds are conservatively set (5 clock ticks, Δ_max + 3 seconds).  Any EXCLUSIVE_OWNERSHIP update within these margins is treated as potentially concurrent and flagged for explicit resolution.  False positives (flagging non-concurrent events as concurrent) are safer than false negatives (missing true conflicts).

---

## 13. INVARIANTS

**I1. Every ledger entry has provenance.**  No value exists in the ledger without source_node, lamport_clock, wall_time, confidence, and observation_type.

**I2. SET_LIKE and COUNTER entries converge.**  Given the same set of updates in any order, all nodes arrive at the same value.  This is guaranteed by the CRDT properties of union and max.

**I3. EXCLUSIVE_OWNERSHIP conflicts are never silently overwritten (within concurrency detection bounds).**  If the concurrency heuristic triggers, the conflict is flagged and both values preserved.

**I4. Lamport clock monotonically increases.**  The clock never decreases on a running node.

**I5. The event log is append-only.**  Events are never modified.  Compaction removes events but does not alter remaining events.

**I6. No ledger operation accesses global state.**  All reads and writes operate on local data and received messages only.

**I7. Semantic type is immutable per key.**  Once a key is created with a semantic type, that type does not change.  This prevents type confusion during merges.

---

## 14. OPEN QUESTIONS

### Q1: When to upgrade from Lamport clocks to vector clocks?

**Question:** At what swarm size or conflict rate do the benefits of vector clocks (exact concurrency detection) outweigh their costs (O(N) per event)?

**Options:**
- **Lamport always (v0.1):** Simple, efficient, approximate concurrency detection via heuristic.
- **Vector clocks:** O(N) space per event but exact concurrency detection.  Membership management needed.
- **Interval tree clocks [Almeida et al., 2008]:** O(1) amortized space, supports dynamic membership.  More complex to implement.
- **Hybrid:** Use Lamport for most types, vector clocks only for EXCLUSIVE_OWNERSHIP.

**Provisional v0.1 choice:** Lamport always.  Monitor conflict false-negative rate.  If > 5% of EXCLUSIVE_OWNERSHIP updates are incorrectly merged, upgrade.

### Q2: How large should event logs be?

**Question:** What is the right retention window for event logs?

**Tradeoff:** Larger logs enable finer-grained reconciliation but consume more memory.  Shorter logs save memory but force full ledger comparisons on long partitions.

**v0.1 choice:** 1000 events AND 600 seconds.  This should cover most short partitions (under 10 minutes).

### Q3: Should SET_LIKE entries support deletion?

**Question:** `visited_zones` is monotonically growing.  But what if a zone needs to be "unvisited" (e.g., zone marked as contaminated and requiring re-survey)?

**Options:**
- **No deletion (v0.1):** Sets only grow.  Simple, convergent.
- **Tombstones:** Mark deleted elements with a tombstone.  Converges but tombstones accumulate.
- **2P-Set [Shapiro 2011]:** Separate add-set and remove-set.  Converges but element can only be removed once.

**Provisional v0.1 choice:** No deletion.  A "re-survey" requirement would be a new task, not a set deletion.

### Q4: CRDTs for all convergent types?

**Question:** Should HESK formally adopt CRDT semantics for SET_LIKE and COUNTER, including the CRDT update API?

**Analysis:** v0.1 already implements G-Set and G-Counter semantics de facto.  Formally adopting the CRDT framework would provide:
- Mathematical convergence guarantees (already have them informally)
- Clear extension path (add-wins LWW-Register for RESOURCE, etc.)
- Prior art acknowledgment and vocabulary

**v0.1 approach:** Acknowledge CRDT equivalence in documentation but do not import a CRDT library.  Keep the implementation simple and self-contained.

### Q5: Handling type conflicts

**Question:** What if Node A creates `key_x` as SET_LIKE and Node B creates `key_x` as COUNTER?

**v0.1 approach:** This should not happen if the schema is defined at mission time.  If it does (bug), reject the update and log an error.  Type is immutable per key (Invariant I7).

---

## 15. BASELINE FOR COMPARISON

### Baseline: Key-value store with wall-clock last-write-wins

Every entry is treated as a simple key-value pair.  On conflict, the entry with the most recent wall-clock timestamp wins.

### Failure 1: SET_LIKE overwrite instead of union

```
Node A: visited_zones = {zone_1, zone_2}  at T=100
Node B: visited_zones = {zone_2, zone_3}  at T=102

B's update arrives at A.  LWW: T=102 > T=100.
Result: visited_zones = {zone_2, zone_3}

WRONG.  zone_1 is lost.
HESK result: {zone_1, zone_2, zone_3}
```

### Failure 2: EXCLUSIVE_OWNERSHIP silently overwritten

```
Partition Alpha: task_owner.mapping = node_3  at T=100
Partition Beta:  task_owner.mapping = node_5  at T=101

Partitions reconnect.  LWW: T=101 > T=100.
Result: task_owner.mapping = node_5

WRONG.  Node 3 may have 60% progress.  Node 5 may have 10%.
The system discards node 3's work without checking.

HESK result: CONFLICT detected, resolved by progress comparison (008).
```

### Failure 3: Clock drift causes wrong RESOURCE winner

```
Node A: node_9.battery = 0.75  at T=100 (A's clock is 2s fast)
Node B: node_9.battery = 0.42  at T=99  (B's clock is accurate; B observed at true T=101)

B's observation is actually MORE RECENT, but LWW picks A (T=100 > T=99).
Result: node_9.battery = 0.75 (stale, wrong)

HESK result: Drift-guarded comparison detects ambiguity (|100-99| = 1s < Δ_max = 2s),
tiebreaks by observation_type (both DIRECT → tiebreak by confidence or node_id).
```

### Comparison metrics

| Metric | LWW Baseline | HESK 007 |
|--------|-------------|----------|
| SET convergence | WRONG (overwrites) | Correct (union) |
| COUNTER convergence | WRONG (may decrease) | Correct (max) |
| Ownership conflicts detected | Never | Yes (heuristic) |
| Clock drift handled | No | Yes (drift guard) |
| Decision traceability | None | Full event log |
| Multi-observation support | No (single value) | Yes (OBSERVATIONAL) |
