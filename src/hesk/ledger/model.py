from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Set

from hesk.core.types import NodeId

class StateSemanticType(Enum):
    SET_LIKE = "SET_LIKE"
    COUNTER = "COUNTER"
    EXCLUSIVE_OWNERSHIP = "EXCLUSIVE_OWNERSHIP"
    OBSERVATIONAL = "OBSERVATIONAL"
    RESOURCE = "RESOURCE"
    MISSION_POLICY = "MISSION_POLICY"
    REACHABILITY = "REACHABILITY"

class ObservationType(Enum):
    DIRECT = "DIRECT"
    RELAYED = "RELAYED"
    INFERRED = "INFERRED"

class EventType(Enum):
    WRITE = "WRITE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"

@dataclass
class Provenance:
    origin: NodeId
    observation_type: ObservationType
    original_clock: int
    hops: int = 0
    relay_chain: List[NodeId] = field(default_factory=list)
    authority_level: int = 100  # Lower is higher authority (used for MISSION_POLICY)

@dataclass
class Observation:
    value: Any
    provenance: Provenance

@dataclass
class ConflictRecord:
    local_value: Any
    remote_value: Any
    remote_source: NodeId
    remote_clock: int
    detected_at: int

@dataclass
class LedgerEntry:
    key: str
    value: Any
    semantic_type: StateSemanticType
    source_node: NodeId
    lamport_clock: int
    wall_time: float
    confidence: float
    provenance: Provenance
    conflict: Optional[ConflictRecord] = None

@dataclass
class Event:
    event_id: str
    type: EventType
    key: str
    semantic_type: StateSemanticType
    old_value: Any
    new_value: Any
    lamport_clock: int
    origin_node: NodeId
    origin_seq: int
    wall_time: float

class BandwidthMode(Enum):
    FULL = "FULL"
    DELTA = "DELTA"
    SUMMARY = "SUMMARY"

@dataclass
class StateExchangeMessage:
    sender_id: NodeId
    sender_clock: int
    version_vector: Dict[NodeId, int]
    entries: List[LedgerEntry]
    bandwidth_mode: BandwidthMode = BandwidthMode.DELTA
