import time
from typing import Dict, List, Any, Optional, Tuple, Callable

from hesk.core.types import NodeId
from hesk.ledger.model import (
    StateSemanticType,
    ObservationType,
    EventType,
    Provenance,
    LedgerEntry,
    Event,
    StateExchangeMessage,
    ReconnectionEvent,
    DivergencePoint,
    SideEffect,
    SideEffectType,
    Resolution,
    Conflict,
    ReconciliationTrace
)
from hesk.ledger.ledger import LocalStateLedger, local_wall_time, DRIFT_MAX

def get_unseen_events(local_log: List[Event], remote_version_vector: Dict[NodeId, int]) -> List[Event]:
    """Return all local events that the remote side has not yet seen."""
    unseen = []
    for event in local_log:
        remote_known_seq = remote_version_vector.get(event.origin_node, 0)
        if event.origin_seq > remote_known_seq:
            unseen.append(event)
    return unseen

def reconstruct_entry(remote_events: List[Event], key: str) -> Optional[LedgerEntry]:
    """Reconstruct the remote entry for a key from a sequence of events."""
    # Find the latest event for this key
    key_events = [e for e in remote_events if e.key == key]
    if not key_events:
        return None
    latest = max(key_events, key=lambda e: e.lamport_clock)
    
    # We create a dummy LedgerEntry based on the event to represent the remote state
    return LedgerEntry(
        key=key,
        value=latest.new_value,
        semantic_type=latest.semantic_type,
        source_node=latest.origin_node,
        lamport_clock=latest.lamport_clock,
        wall_time=latest.wall_time,
        confidence=1.0, # Defaulting for event reconstruction
        provenance=Provenance(origin=latest.origin_node, observation_type=ObservationType.DIRECT, original_clock=latest.lamport_clock)
    )

def detect_conflicts(local_ledger: LocalStateLedger, local_events: List[Event], remote_events: List[Event]) -> List[Conflict]:
    """Find keys modified on both sides since divergence."""
    local_modified_keys = {e.key for e in local_events}
    remote_modified_keys = {e.key for e in remote_events}
    
    potentially_conflicting = local_modified_keys & remote_modified_keys
    
    conflicts = []
    for key in potentially_conflicting:
        local_entry = local_ledger.entries.get(key)
        remote_entry = reconstruct_entry(remote_events, key)
        
        if not local_entry or not remote_entry:
            continue
            
        # SET_LIKE and COUNTER never conflict (handled by merge)
        if local_entry.semantic_type in (StateSemanticType.SET_LIKE, StateSemanticType.COUNTER):
            continue
            
        # OBSERVATIONAL doesn't conflict
        if local_entry.semantic_type == StateSemanticType.OBSERVATIONAL:
            continue
            
        if local_entry.value != remote_entry.value:
            conflicts.append(Conflict(
                key=key,
                local_entry=local_entry,
                remote_entry=remote_entry,
                semantic_type=local_entry.semantic_type
            ))
            
    return conflicts

def _extract_task_info(value: Any) -> Tuple[NodeId, float, float]:
    """Helper to extract assignee, progress, quality from a value."""
    if isinstance(value, dict):
        return value.get("assignee", ""), value.get("progress", 0.0), value.get("match_quality", 0.0)
    return value, 0.0, 0.0

def resolve_exclusive_ownership(conflict: Conflict) -> Resolution:
    """Resolve dual ownership of a task. Progress -> Quality -> Node ID."""
    local = conflict.local_entry
    remote = conflict.remote_entry
    
    local_assignee, local_prog, local_qual = _extract_task_info(local.value)
    remote_assignee, remote_prog, remote_qual = _extract_task_info(remote.value)
    
    PROGRESS_EPSILON = 0.05
    QUALITY_EPSILON = 0.05
    
    winner, loser = None, None
    reason = ""
    
    if abs(local_prog - remote_prog) > PROGRESS_EPSILON:
        if local_prog > remote_prog:
            winner, loser = local, remote
            reason = f"Higher progress: {local_assignee} at {local_prog:.2f} vs {remote_assignee} at {remote_prog:.2f}"
        else:
            winner, loser = remote, local
            reason = f"Higher progress: {remote_assignee} at {remote_prog:.2f} vs {local_assignee} at {local_prog:.2f}"
    elif abs(local_qual - remote_qual) > QUALITY_EPSILON:
        if local_qual > remote_qual:
            winner, loser = local, remote
            reason = f"Higher match quality: {local_assignee} at {local_qual:.2f}"
        else:
            winner, loser = remote, local
            reason = f"Higher match quality: {remote_assignee} at {remote_qual:.2f}"
    else:
        # Tiebreak on assignment time, then node ID
        if local.wall_time < remote.wall_time:
            winner, loser = local, remote
            reason = f"Earlier assignment: {local.wall_time} < {remote.wall_time}"
        elif remote.wall_time < local.wall_time:
            winner, loser = remote, local
            reason = f"Earlier assignment: {remote.wall_time} < {local.wall_time}"
        else:
            if str(local_assignee) < str(remote_assignee):
                winner, loser = local, remote
                reason = f"Tiebreak: lower node_id {local_assignee} < {remote_assignee}"
            else:
                winner, loser = remote, local
                reason = f"Tiebreak: lower node_id {remote_assignee} < {local_assignee}"

    winner_assignee = _extract_task_info(winner.value)[0]
    loser_assignee = _extract_task_info(loser.value)[0]

    return Resolution(
        strategy="EXCLUSIVE_OWNERSHIP_CASCADE",
        winning_value=winner.value,
        winning_source=winner.source_node,
        reason=reason,
        side_effects=[
            SideEffect(type=SideEffectType.RELEASE_EXECUTOR, target=loser_assignee, task=conflict.key),
            SideEffect(type=SideEffectType.NOTIFY_WINNER, target=winner_assignee, task=conflict.key)
        ]
    )

def resolve_resource(conflict: Conflict) -> Resolution:
    """Most recent observation wins, with drift guard."""
    local = conflict.local_entry
    remote = conflict.remote_entry
    
    time_diff = remote.wall_time - local.wall_time
    
    if time_diff > DRIFT_MAX:
        return Resolution(
            strategy="RESOURCE_RECENCY",
            winning_value=remote.value,
            winning_source=remote.source_node,
            reason=f"Remote observation is {time_diff:.1f}s newer"
        )
    elif time_diff < -DRIFT_MAX:
        return Resolution(
            strategy="RESOURCE_RECENCY",
            winning_value=local.value,
            winning_source=local.source_node,
            reason=f"Local observation is {-time_diff:.1f}s newer"
        )
    else:
        # Provenance tiebreak
        def prov_score(e: LedgerEntry) -> float:
            scores = {ObservationType.DIRECT: 1.0, ObservationType.RELAYED: 0.7, ObservationType.INFERRED: 0.5}
            return scores.get(e.provenance.observation_type, 0.0) * e.confidence
            
        local_score = prov_score(local)
        remote_score = prov_score(remote)
        
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

def resolve_mission_policy(conflict: Conflict) -> Resolution:
    """Higher authority wins."""
    local_auth = conflict.local_entry.provenance.authority_level
    remote_auth = conflict.remote_entry.provenance.authority_level
    
    if local_auth <= remote_auth:
        return Resolution(
            strategy="MISSION_POLICY_AUTHORITY",
            winning_value=conflict.local_entry.value,
            winning_source=conflict.local_entry.source_node,
            reason=f"Local authority level {local_auth} <= remote {remote_auth}"
        )
    else:
        return Resolution(
            strategy="MISSION_POLICY_AUTHORITY",
            winning_value=conflict.remote_entry.value,
            winning_source=conflict.remote_entry.source_node,
            reason=f"Remote authority level {remote_auth} < local {local_auth}"
        )

def handle_reconnection(
    local_ledger: LocalStateLedger, 
    remote_node_id: NodeId, 
    remote_clock: int,
    remote_version_vector: Dict[NodeId, int],
    remote_events: List[Event],
    execute_side_effect: Callable[[SideEffect], None] = lambda e: None
) -> ReconciliationTrace:
    """Main entry point for partition reconciliation."""
    
    start_time = local_wall_time()
    
    reconnection = ReconnectionEvent(
        detecting_node=local_ledger.node_id,
        remote_node=remote_node_id,
        detection_time=start_time,
        detecting_clock=local_ledger.lamport_clock,
        remote_clock=remote_clock
    )
    
    # Calculate divergence point for tracing (simplified)
    divergence = DivergencePoint(
        clock_value=0, # Simplified
        local_events_since=0,
        remote_events_since=len(remote_events)
    )
    
    local_events = get_unseen_events(local_ledger.event_log, remote_version_vector)
    divergence.local_events_since = len(local_events)
    
    entries_merged = 0
    
    # Merge convergent types
    for event in remote_events:
        if event.semantic_type in (StateSemanticType.SET_LIKE, StateSemanticType.COUNTER, StateSemanticType.OBSERVATIONAL):
            # Create a mock provenance
            prov = Provenance(origin=event.origin_node, observation_type=ObservationType.DIRECT, original_clock=event.lamport_clock)
            _, changed = local_ledger.write_received(
                key=event.key,
                value=event.new_value,
                semantic_type=event.semantic_type,
                source_node=event.origin_node,
                source_clock=event.lamport_clock,
                source_wall_time=event.wall_time,
                confidence=1.0,
                provenance=prov
            )
            if changed:
                entries_merged += 1
                
    conflicts = detect_conflicts(local_ledger, local_events, remote_events)
    
    for conflict in conflicts:
        if conflict.semantic_type == StateSemanticType.EXCLUSIVE_OWNERSHIP:
            conflict.resolution = resolve_exclusive_ownership(conflict)
        elif conflict.semantic_type == StateSemanticType.RESOURCE:
            conflict.resolution = resolve_resource(conflict)
        elif conflict.semantic_type == StateSemanticType.MISSION_POLICY:
            conflict.resolution = resolve_mission_policy(conflict)
        else:
            # Fallback
            conflict.resolution = Resolution(
                strategy="FALLBACK",
                winning_value=conflict.local_entry.value,
                winning_source=conflict.local_entry.source_node,
                reason="Fallback resolution"
            )
            
        local_ledger.write_local(
            key=conflict.key,
            value=conflict.resolution.winning_value,
            semantic_type=conflict.semantic_type
        )
        entries_merged += 1
        
    trace = ReconciliationTrace(
        reconnection=reconnection,
        divergence=divergence,
        conflicts_found=len(conflicts),
        conflicts_resolved=len([c for c in conflicts if c.resolution]),
        resolution_details=conflicts,
        entries_merged=entries_merged,
        duration_ms=(local_wall_time() - start_time) * 1000
    )
    
    # Execute side effects
    for conflict in conflicts:
        if conflict.resolution and conflict.resolution.side_effects:
            for effect in conflict.resolution.side_effects:
                execute_side_effect(effect)
                
    return trace

def reconcile_full_ledger(
    local_ledger: LocalStateLedger, 
    remote_node_id: NodeId,
    remote_entries: Dict[str, LedgerEntry],
    execute_side_effect: Callable[[SideEffect], None] = lambda e: None
) -> ReconciliationTrace:
    """Fallback: when event logs are unavailable, compare full ledgers."""
    start_time = local_wall_time()
    
    reconnection = ReconnectionEvent(
        detecting_node=local_ledger.node_id,
        remote_node=remote_node_id,
        detection_time=start_time,
        detecting_clock=local_ledger.lamport_clock,
        remote_clock=max([e.lamport_clock for e in remote_entries.values()] + [0])
    )
    
    conflicts = []
    entries_merged = 0
    
    for key, remote_entry in remote_entries.items():
        local_entry = local_ledger.entries.get(key)
        
        if local_entry is None:
            # We don't have this key - accept remote
            local_ledger.entries[key] = remote_entry
            entries_merged += 1
            continue
            
        if remote_entry.semantic_type in (StateSemanticType.SET_LIKE, StateSemanticType.COUNTER, StateSemanticType.OBSERVATIONAL):
            _, changed = local_ledger.write_received(
                key=key,
                value=remote_entry.value,
                semantic_type=remote_entry.semantic_type,
                source_node=remote_entry.source_node,
                source_clock=remote_entry.lamport_clock,
                source_wall_time=remote_entry.wall_time,
                confidence=remote_entry.confidence,
                provenance=remote_entry.provenance
            )
            if changed:
                entries_merged += 1
        elif remote_entry.value != local_entry.value:
            conflicts.append(Conflict(
                key=key,
                local_entry=local_entry,
                remote_entry=remote_entry,
                semantic_type=local_entry.semantic_type
            ))
            
    for conflict in conflicts:
        if conflict.semantic_type == StateSemanticType.EXCLUSIVE_OWNERSHIP:
            conflict.resolution = resolve_exclusive_ownership(conflict)
        elif conflict.semantic_type == StateSemanticType.RESOURCE:
            conflict.resolution = resolve_resource(conflict)
        elif conflict.semantic_type == StateSemanticType.MISSION_POLICY:
            conflict.resolution = resolve_mission_policy(conflict)
            
        if conflict.resolution:
            local_ledger.write_local(
                key=conflict.key,
                value=conflict.resolution.winning_value,
                semantic_type=conflict.semantic_type
            )
            entries_merged += 1
            
            for effect in conflict.resolution.side_effects:
                execute_side_effect(effect)

    trace = ReconciliationTrace(
        reconnection=reconnection,
        divergence=DivergencePoint(clock_value=0, local_events_since=0, remote_events_since=0),
        conflicts_found=len(conflicts),
        conflicts_resolved=len([c for c in conflicts if c.resolution]),
        resolution_details=conflicts,
        entries_merged=entries_merged,
        duration_ms=(local_wall_time() - start_time) * 1000
    )
    
    return trace
