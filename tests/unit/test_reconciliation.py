import pytest
from hesk.core.types import NodeId
from hesk.ledger.model import (
    StateSemanticType,
    ObservationType,
    Provenance,
    LedgerEntry,
    Event,
    EventType,
    SideEffectType,
    Conflict,
    ReconnectionEvent
)
from hesk.ledger.ledger import LocalStateLedger
from hesk.ledger.reconciliation import (
    get_unseen_events,
    detect_conflicts,
    resolve_exclusive_ownership,
    resolve_resource,
    resolve_mission_policy,
    handle_reconnection,
    reconcile_full_ledger
)

def create_provenance(origin: NodeId, obs_type: ObservationType, clock: int = 1, auth: int = 100):
    return Provenance(origin=origin, observation_type=obs_type, original_clock=clock, authority_level=auth)

def test_resolve_exclusive_ownership():
    # Conflict: Alpha assigned node_3 (60% prog), Beta assigned node_5 (30% prog)
    local_entry = LedgerEntry(
        key="task_owner.mapping_x",
        value={"assignee": "node_3", "progress": 0.60, "match_quality": 0.75},
        semantic_type=StateSemanticType.EXCLUSIVE_OWNERSHIP,
        source_node="node_1",
        lamport_clock=12,
        wall_time=135.0,
        confidence=1.0,
        provenance=create_provenance("node_1", ObservationType.DIRECT)
    )
    
    remote_entry = LedgerEntry(
        key="task_owner.mapping_x",
        value={"assignee": "node_5", "progress": 0.30, "match_quality": 0.82},
        semantic_type=StateSemanticType.EXCLUSIVE_OWNERSHIP,
        source_node="node_4",
        lamport_clock=14,
        wall_time=150.0,
        confidence=1.0,
        provenance=create_provenance("node_4", ObservationType.DIRECT)
    )
    
    conflict = Conflict(
        key="task_owner.mapping_x",
        local_entry=local_entry,
        remote_entry=remote_entry,
        semantic_type=StateSemanticType.EXCLUSIVE_OWNERSHIP
    )
    
    resolution = resolve_exclusive_ownership(conflict)
    
    # Progress wins: node_3 (0.60 > 0.30)
    assert resolution.winning_value["assignee"] == "node_3"
    assert resolution.winning_source == "node_1"
    
    # Should release node_5
    assert len(resolution.side_effects) == 2
    assert resolution.side_effects[0].type == SideEffectType.RELEASE_EXECUTOR
    assert resolution.side_effects[0].target == "node_5"

def test_resolve_resource_recency():
    local_entry = LedgerEntry(
        key="node_6.status",
        value="SUSPECTED_UNREACHABLE",
        semantic_type=StateSemanticType.RESOURCE,
        source_node="node_1",
        lamport_clock=10,
        wall_time=120.0,
        confidence=1.0,
        provenance=create_provenance("node_1", ObservationType.INFERRED)
    )
    
    remote_entry = LedgerEntry(
        key="node_6.status",
        value="ACTIVE",
        semantic_type=StateSemanticType.RESOURCE,
        source_node="node_4",
        lamport_clock=15,
        wall_time=160.0, # 40 seconds newer
        confidence=1.0,
        provenance=create_provenance("node_4", ObservationType.DIRECT)
    )
    
    conflict = Conflict(
        key="node_6.status",
        local_entry=local_entry,
        remote_entry=remote_entry,
        semantic_type=StateSemanticType.RESOURCE
    )
    
    resolution = resolve_resource(conflict)
    
    assert resolution.strategy == "RESOURCE_RECENCY"
    assert resolution.winning_value == "ACTIVE"
    assert resolution.winning_source == "node_4"

def test_resolve_mission_policy():
    local_entry = LedgerEntry(
        key="priority.override",
        value="Alpha_Rule",
        semantic_type=StateSemanticType.MISSION_POLICY,
        source_node="node_1",
        lamport_clock=10,
        wall_time=100.0,
        confidence=1.0,
        provenance=create_provenance("node_1", ObservationType.DIRECT, auth=5) # higher authority
    )
    
    remote_entry = LedgerEntry(
        key="priority.override",
        value="Beta_Rule",
        semantic_type=StateSemanticType.MISSION_POLICY,
        source_node="node_4",
        lamport_clock=12,
        wall_time=120.0,
        confidence=1.0,
        provenance=create_provenance("node_4", ObservationType.DIRECT, auth=10) # lower authority
    )
    
    conflict = Conflict(
        key="priority.override",
        local_entry=local_entry,
        remote_entry=remote_entry,
        semantic_type=StateSemanticType.MISSION_POLICY
    )
    
    resolution = resolve_mission_policy(conflict)
    assert resolution.winning_value == "Alpha_Rule"
    assert resolution.strategy == "MISSION_POLICY_AUTHORITY"

def test_handle_reconnection_integration():
    alpha_ledger = LocalStateLedger(node_id="node_2")
    
    # Pre-partition shared state
    alpha_ledger.write_local("visited_zones", {"zone_a"}, StateSemanticType.SET_LIKE)
    alpha_ledger.write_local("tasks_completed", 5, StateSemanticType.COUNTER)
    
    # Partition happens here. Alpha gets new events.
    alpha_ledger.write_local("visited_zones", {"zone_a", "zone_b"}, StateSemanticType.SET_LIKE)
    alpha_ledger.write_local("task_owner.mapping", {"assignee": "node_3", "progress": 0.60, "match_quality": 0.75}, StateSemanticType.EXCLUSIVE_OWNERSHIP)
    alpha_ledger.write_local("tasks_completed", 7, StateSemanticType.COUNTER)
    
    # Remote Beta events
    remote_events = [
        Event(
            event_id="node_4_13", type=EventType.WRITE, key="visited_zones", semantic_type=StateSemanticType.SET_LIKE,
            old_value=None, new_value={"zone_a", "zone_c", "zone_d"}, lamport_clock=13, origin_node="node_4", origin_seq=5, wall_time=145.0
        ),
        Event(
            event_id="node_4_14", type=EventType.WRITE, key="task_owner.mapping", semantic_type=StateSemanticType.EXCLUSIVE_OWNERSHIP,
            old_value=None, new_value={"assignee": "node_5", "progress": 0.30, "match_quality": 0.82}, lamport_clock=14, origin_node="node_4", origin_seq=6, wall_time=150.0
        ),
        Event(
            event_id="node_4_16", type=EventType.WRITE, key="tasks_completed", semantic_type=StateSemanticType.COUNTER,
            old_value=None, new_value=8, lamport_clock=16, origin_node="node_4", origin_seq=7, wall_time=170.0
        )
    ]
    
    side_effects = []
    
    trace = handle_reconnection(
        local_ledger=alpha_ledger,
        remote_node_id="node_4",
        remote_clock=16,
        remote_version_vector={"node_4": 4},
        remote_events=remote_events,
        execute_side_effect=lambda e: side_effects.append(e)
    )
    
    assert trace.conflicts_found == 1
    assert trace.conflicts_resolved == 1
    
    # Check post-reconciliation ledger state
    assert alpha_ledger.entries["visited_zones"].value == {"zone_a", "zone_b", "zone_c", "zone_d"}
    assert alpha_ledger.entries["tasks_completed"].value == 8
    
    # Exclusive ownership resolved to node_3
    assert alpha_ledger.entries["task_owner.mapping"].value["assignee"] == "node_3"
    
    # Check side effects
    assert len(side_effects) == 2
    assert side_effects[0].type == SideEffectType.RELEASE_EXECUTOR
    assert side_effects[0].target == "node_5"
