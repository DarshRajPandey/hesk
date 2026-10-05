from typing import Dict, List, Any, Optional, Tuple

from hesk.core import clock
from hesk.core.types import NodeId
from hesk.ledger.model import (
    StateSemanticType,
    ObservationType,
    EventType,
    Provenance,
    Observation,
    ConflictRecord,
    LedgerEntry,
    Event,
    StateExchangeMessage
)

# Configuration defaults
CONCURRENCY_CLOCK_THRESHOLD = 5
CONCURRENCY_WALL_THRESHOLD = 3.0
DRIFT_MAX = 2.0
MAX_OBSERVATIONS_PER_KEY = 5
MAX_CLOCK_AGE = 1000
MAX_WALL_AGE_S = 600.0

def local_wall_time() -> float:
    """Mockable wall time (delegates to the injectable clock)."""
    return clock.now()

def is_potentially_concurrent(local_entry: LedgerEntry, source_clock: int, source_wall_time: float) -> bool:
    """Detect if two updates to an EXCLUSIVE_OWNERSHIP key might be concurrent."""
    clock_diff = abs(local_entry.lamport_clock - source_clock)
    wall_diff = abs(local_entry.wall_time - source_wall_time)
    
    if clock_diff <= CONCURRENCY_CLOCK_THRESHOLD and wall_diff <= DRIFT_MAX + CONCURRENCY_WALL_THRESHOLD:
        return True
        
    if wall_diff <= DRIFT_MAX + CONCURRENCY_WALL_THRESHOLD:
        return True
        
    return False

def accept_resource_update(local_entry: LedgerEntry, source_wall_time: float, confidence: float, provenance: Provenance) -> bool:
    """Determine if a received RESOURCE update is newer, accounting for wall-clock drift."""
    time_diff = source_wall_time - local_entry.wall_time
    
    if time_diff > DRIFT_MAX:
        return True
    elif time_diff < -DRIFT_MAX:
        return False
    else:
        # Ambiguous - tiebreak
        if provenance.observation_type == ObservationType.DIRECT and local_entry.provenance.observation_type != ObservationType.DIRECT:
            return True
        elif confidence > local_entry.confidence:
            return True
        return False

class LocalStateLedger:
    def __init__(self, node_id: NodeId):
        self.node_id = node_id
        self.entries: Dict[str, LedgerEntry] = {}
        self.event_log: List[Event] = []
        self.lamport_clock = 0
        self.seq_num = 0
        self.version_vector: Dict[NodeId, int] = {node_id: 0}

    def write_local(self, key: str, value: Any, semantic_type: StateSemanticType) -> LedgerEntry:
        """Record a local observation or decision."""
        self.lamport_clock += 1
        self.seq_num += 1
        self.version_vector[self.node_id] = self.seq_num
        
        old_value = self.entries.get(key)
        
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
                observation_type=ObservationType.DIRECT,
                original_clock=self.lamport_clock,
                hops=0
            )
        )
        
        self.entries[key] = entry
        
        self._append_event(
            event_type=EventType.UPDATE if old_value else EventType.WRITE,
            key=key,
            semantic_type=semantic_type,
            old_value=old_value.value if old_value else None,
            new_value=value,
            origin_node=self.node_id,
            origin_seq=self.seq_num
        )
        
        return entry

    def process_message(self, message: StateExchangeMessage) -> List[Tuple[LedgerEntry, bool]]:
        """Process a batch of state updates received in a single message."""
        self.lamport_clock = max(self.lamport_clock, message.sender_clock) + 1
        
        results = []
        for entry in message.entries:
            result = self.write_received(
                key=entry.key,
                value=entry.value,
                semantic_type=entry.semantic_type,
                source_node=entry.source_node,
                source_clock=entry.lamport_clock,
                source_wall_time=entry.wall_time,
                confidence=entry.confidence,
                provenance=entry.provenance,
                update_lamport_clock=False
            )
            results.append(result)
        return results

    def write_received(
        self, key: str, value: Any, semantic_type: StateSemanticType,
        source_node: NodeId, source_clock: int, source_wall_time: float,
        confidence: float, provenance: Provenance, origin_seq: int = 0,
        update_lamport_clock: bool = True
    ) -> Tuple[LedgerEntry, bool]:
        """Process a state update received from another node."""
        if update_lamport_clock:
            self.lamport_clock = max(self.lamport_clock, source_clock) + 1
        
        local_entry = self.entries.get(key)
        
        if local_entry is None:
            new_entry = LedgerEntry(
                key=key, value=value, semantic_type=semantic_type,
                source_node=source_node, lamport_clock=self.lamport_clock,
                wall_time=source_wall_time, confidence=confidence,
                provenance=provenance
            )
            self.entries[key] = new_entry
            self._append_event(EventType.WRITE, key, semantic_type, None, value, source_node, origin_seq)
            return new_entry, True
            
        merged_value, changed, conflict = self._semantic_merge(
            local_entry, value, source_node, source_clock, 
            source_wall_time, confidence, provenance
        )
        
        if changed:
            old_val = local_entry.value
            local_entry.value = merged_value
            local_entry.lamport_clock = self.lamport_clock
            local_entry.wall_time = max(local_entry.wall_time, source_wall_time)
            local_entry.source_node = source_node
            local_entry.confidence = confidence
            local_entry.provenance = provenance
            self._append_event(EventType.UPDATE, key, semantic_type, old_val, merged_value, source_node, origin_seq)
            
        if conflict:
            local_entry.conflict = ConflictRecord(
                local_value=local_entry.value,
                remote_value=value,
                remote_source=source_node,
                remote_clock=source_clock,
                detected_at=self.lamport_clock
            )
            self._append_event(EventType.CONFLICT_DETECTED, key, semantic_type, local_entry.value, value, source_node, origin_seq)
            
        return local_entry, changed

    def _semantic_merge(
        self, local_entry: LedgerEntry, received_value: Any, source_node: NodeId,
        source_clock: int, source_wall_time: float, confidence: float, provenance: Provenance
    ) -> Tuple[Any, bool, bool]:
        """Apply type-specific merge rules. Returns (merged_value, changed, conflict)."""
        stype = local_entry.semantic_type
        
        if stype == StateSemanticType.SET_LIKE:
            if not isinstance(local_entry.value, set):
                local_entry.value = set(local_entry.value)
            if not isinstance(received_value, set):
                received_value = set(received_value)
                
            merged = local_entry.value | received_value
            changed = merged != local_entry.value
            return merged, changed, False
            
        elif stype == StateSemanticType.COUNTER:
            merged = max(local_entry.value, received_value)
            changed = merged != local_entry.value
            return merged, changed, False
            
        elif stype == StateSemanticType.EXCLUSIVE_OWNERSHIP:
            if is_potentially_concurrent(local_entry, source_clock, source_wall_time):
                return local_entry.value, False, True
            elif source_clock > local_entry.lamport_clock:
                return received_value, True, False
            elif source_clock < local_entry.lamport_clock:
                return local_entry.value, False, False
            else:
                if source_node < local_entry.source_node:
                    return received_value, True, False
                return local_entry.value, False, False
                    
        elif stype == StateSemanticType.OBSERVATIONAL:
            if not isinstance(local_entry.value, list):
                local_entry.value = [Observation(value=local_entry.value, provenance=local_entry.provenance)]
                
            local_entry.value.append(Observation(value=received_value, provenance=provenance))
            
            if len(local_entry.value) > MAX_OBSERVATIONS_PER_KEY:
                local_entry.value.sort(key=lambda o: o.provenance.original_clock, reverse=True)
                local_entry.value = local_entry.value[:MAX_OBSERVATIONS_PER_KEY]
            return local_entry.value, True, False
            
        elif stype == StateSemanticType.RESOURCE:
            if accept_resource_update(local_entry, source_wall_time, confidence, provenance):
                return received_value, True, False
            return local_entry.value, False, False
            
        elif stype == StateSemanticType.MISSION_POLICY:
            if provenance.authority_level < local_entry.provenance.authority_level:
                return received_value, True, False
            return local_entry.value, False, False
            
        elif stype == StateSemanticType.REACHABILITY:
            # Simplistic for v0.1: just accept latest graph edges
            if source_clock > local_entry.lamport_clock:
                return received_value, True, False
            return local_entry.value, False, False
            
        return local_entry.value, False, False

    def read(self, key: str) -> Tuple[Optional[Any], Optional[Dict[str, Any]]]:
        """Query a ledger entry."""
        entry = self.entries.get(key)
        if entry is None:
            return None, None
            
        return entry.value, {
            'semantic_type': entry.semantic_type,
            'source_node': entry.source_node,
            'lamport_clock': entry.lamport_clock,
            'wall_time': entry.wall_time,
            'confidence': entry.confidence,
            'provenance': entry.provenance,
            'has_conflict': entry.conflict is not None
        }

    def get_events_since(self, clock_value: int) -> List[Event]:
        """Return all events with lamport_clock > clock_value."""
        return [e for e in self.event_log if e.lamport_clock > clock_value]

    def compact_log(self) -> int:
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

    def _append_event(
        self, event_type: EventType, key: str, semantic_type: StateSemanticType, 
        old_value: Any, new_value: Any, origin_node: NodeId, origin_seq: int
    ):
        """Append an event to the log."""
        self.event_log.append(Event(
            event_id=f"{self.node_id}_{self.lamport_clock}",
            type=event_type,
            key=key,
            semantic_type=semantic_type,
            old_value=old_value,
            new_value=new_value,
            lamport_clock=self.lamport_clock,
            origin_node=origin_node,
            origin_seq=origin_seq,
            wall_time=local_wall_time()
        ))
