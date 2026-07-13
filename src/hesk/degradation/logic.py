import time
from typing import Dict, List, Set, Any, Optional, Union, Tuple
from collections import defaultdict

from hesk.core.types import NodeId, PriorityClass
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskDefinition, DegradationTier
from hesk.capabilities.matching import check_eligibility
from hesk.tasks.allocation import compute_system_cost

from hesk.coalitions.model import Coalition
from hesk.coalitions.formation import form_coalition, LinkMetrics
from hesk.degradation.model import (
    DegradationTrigger,
    MissionPriorityClass,
    DegradationPlan,
    TraceEntry,
    TraceAction,
    SatisfactionAction,
    SatisfactionResult
)

# Configuration defaults
DEGRADATION_CASCADE_LIMIT = 3
INFINITY = float('inf')

class TaskStatus:
    EXECUTING = "EXECUTING"
    DEGRADED = "DEGRADED"
    ABANDONED = "ABANDONED"
    COMPLETED = "COMPLETED"

class ActiveTask:
    """Runtime representation of a task being executed."""
    def __init__(self, task_def: TaskDefinition, current_tier: int, status: str, assignee: Union[NodeId, Coalition, None] = None):
        self.task_def = task_def
        self.current_tier = current_tier
        self.status = status
        self.assignee = assignee

    @property
    def id(self) -> str:
        return self.task_def.task_id

    @property
    def priority_class(self) -> PriorityClass:
        return self.task_def.priority_class

    @property
    def priority(self) -> float:
        return self.task_def.mission_priority

    @property
    def degradation_tiers(self) -> List[DegradationTier]:
        return self.task_def.tiers

    @property
    def minimum_acceptable_quality(self) -> float:
        return self.task_def.q_min

    @property
    def current_quality(self) -> float:
        if self.status == TaskStatus.ABANDONED:
            return 0.0
        return self.degradation_tiers[self.current_tier].quality_estimate
        
    def with_tier(self, tier: DegradationTier):
        """Helper to create a temporary task def pinned to a specific tier."""
        return self.task_def

class LocalLedger:
    """Mock interface for local state ledger."""
    def get_affected_tasks(self, trigger: DegradationTrigger) -> List[ActiveTask]:
        return []
        
    def get_all_active_tasks(self) -> List[ActiveTask]:
        return []

    def release_task_resources(self, task: ActiveTask) -> List[NodeId]:
        return []

class AvailableNodes:
    """Tracker for nodes available for assignment."""
    def __init__(self, known_nodes: List[CapabilityState], trigger: DegradationTrigger):
        self.nodes = {n.node_id: n for n in known_nodes}
        if trigger.source_node in self.nodes:
            del self.nodes[trigger.source_node]
            
    def get_list(self) -> List[CapabilityState]:
        return list(self.nodes.values())
        
    def remove_commitment(self, node_id: NodeId):
        if node_id in self.nodes:
            del self.nodes[node_id]
            
    def add_freed(self, nodes: List[CapabilityState]):
        for n in nodes:
            self.nodes[n.node_id] = n

def compute_swarm_utility(tasks: List[ActiveTask]) -> float:
    """U_swarm = Σ(π_j × quality_j) for all active tasks."""
    return sum(t.priority * t.current_quality for t in tasks if t.status in [TaskStatus.EXECUTING, TaskStatus.DEGRADED])

def compute_swarm_utility_with_changes(
    tasks: List[ActiveTask], 
    tier_changes: Dict[str, Tuple[Optional[int], Optional[int]]],
    abandoned: List[str]
) -> float:
    utility = 0.0
    for t in tasks:
        if t.id in abandoned:
            continue
            
        if t.id in tier_changes:
            new_tier = tier_changes[t.id][1]
            if new_tier is not None:
                utility += t.priority * t.degradation_tiers[new_tier].quality_estimate
        elif t.status in [TaskStatus.EXECUTING, TaskStatus.DEGRADED]:
            utility += t.priority * t.current_quality
            
    return utility

def find_best_satisfaction_with_descent(
    task: ActiveTask, 
    available: AvailableNodes, 
    link_metrics: LinkMetrics
) -> SatisfactionResult:
    """Try to satisfy task at current tier, then descend through degradation tiers."""
    
    available_list = available.get_list()
    
    for tier_idx in range(task.current_tier, len(task.degradation_tiers)):
        tier = task.degradation_tiers[tier_idx]
        
        if tier.quality_estimate < task.minimum_acceptable_quality:
            continue
            
        reqs = tier.required
        
        # Try solo
        eligible = [n for n in available_list if check_eligibility(n, reqs)]
        if eligible:
            # Need bids structure for compute_system_cost, using simple selection here
            best = min(eligible, key=lambda n: 1.0) # simplify for now
            return SatisfactionResult(
                action=SatisfactionAction.SOLO_REASSIGN, 
                assignee=best.node_id, 
                tier=tier_idx
            )
            
        # Try coalition
        coalition_result = form_coalition(
            task_id=task.id,
            required=reqs,
            data_flows=tier.data_flow,
            candidates=available_list,
            link_metrics=link_metrics,
            initiator_id="local_node"
        )
        if coalition_result.success:
            return SatisfactionResult(
                action=SatisfactionAction.COALITION_FORM, 
                coalition=coalition_result.coalition, 
                tier=tier_idx
            )
            
    return SatisfactionResult(action=SatisfactionAction.ABANDON)

def attempt_upgrades(
    all_tasks: List[ActiveTask], 
    available: AvailableNodes, 
    link_metrics: LinkMetrics
) -> List[Tuple[str, int, Union[NodeId, Coalition]]]:
    """Check if any degraded task can be upgraded with currently available resources."""
    upgrades = []
    # simplified upgrade logic
    return upgrades

def handle_degradation_trigger(
    trigger: DegradationTrigger, 
    local_ledger: LocalLedger, 
    known_nodes: List[CapabilityState], 
    link_metrics: LinkMetrics
) -> Optional[DegradationPlan]:
    """
    Main entry point for degradation response.
    """
    affected_tasks = local_ledger.get_affected_tasks(trigger)
    if not affected_tasks:
        return None
        
    all_tasks = local_ledger.get_all_active_tasks()
    utility_before = compute_swarm_utility(all_tasks)
    
    # Priority sorting mapping
    priority_order = {
        PriorityClass.CRITICAL: 3,
        PriorityClass.IMPORTANT: 2,
        PriorityClass.OPTIONAL: 1
    }
    
    affected_tasks.sort(key=lambda t: (priority_order.get(t.priority_class, 0), t.priority), reverse=True)
    
    available_nodes = AvailableNodes(known_nodes, trigger)
    
    tier_changes = {}
    new_assignments = {}
    abandoned = []
    trace = []
    
    for task in affected_tasks:
        result = find_best_satisfaction_with_descent(task, available_nodes, link_metrics)
        
        if result.action == SatisfactionAction.SOLO_REASSIGN:
            new_assignments[task.id] = result.assignee
            tier_changes[task.id] = (task.current_tier, result.tier)
            available_nodes.remove_commitment(result.assignee)
            trace.append(TraceEntry(
                timestamp=time.time(),
                task_id=task.id, 
                action=TraceAction.REASSIGN,
                reason=f"Solo reassignment to {result.assignee} at tier {result.tier}",
                old_tier=task.current_tier, 
                new_tier=result.tier,
                old_assignee=task.assignee,
                new_assignee=result.assignee,
                quality_change=(task.current_quality, task.degradation_tiers[result.tier].quality_estimate)
            ))
            
        elif result.action == SatisfactionAction.COALITION_FORM:
            new_assignments[task.id] = result.coalition
            tier_changes[task.id] = (task.current_tier, result.tier)
            for member in result.coalition.members:
                available_nodes.remove_commitment(member)
            trace.append(TraceEntry(
                timestamp=time.time(),
                task_id=task.id, 
                action=TraceAction.DEGRADE,
                reason=f"Coalition {result.coalition.members} at tier {result.tier}",
                old_tier=task.current_tier, 
                new_tier=result.tier,
                old_assignee=task.assignee,
                new_assignee=result.coalition,
                quality_change=(task.current_quality, task.degradation_tiers[result.tier].quality_estimate)
            ))
            
        elif result.action == SatisfactionAction.ABANDON:
            abandoned.append(task.id)
            # Free nodes (mock)
            freed_node_ids = local_ledger.release_task_resources(task)
            # Find the actual CapabilityState objects for these IDs
            freed_states = [n for n in known_nodes if n.node_id in freed_node_ids and n.node_id != trigger.source_node]
            available_nodes.add_freed(freed_states)
            
            trace.append(TraceEntry(
                timestamp=time.time(),
                task_id=task.id, 
                action=TraceAction.ABANDON,
                reason="No tier satisfiable.",
                old_tier=task.current_tier, 
                new_tier=None,
                old_assignee=task.assignee,
                new_assignee=None,
                quality_change=(task.current_quality, 0.0)
            ))
            
            if task.priority_class == PriorityClass.CRITICAL:
                trace.append(TraceEntry(
                    timestamp=time.time(),
                    task_id=task.id, 
                    action=TraceAction.ALARM,
                    reason="CRITICAL task abandoned — mission integrity compromised"
                ))
                
    # Cascade logic (mock implementation for unit tests)
    cascade_round = 0
    while cascade_round < DEGRADATION_CASCADE_LIMIT:
        upgrades = attempt_upgrades(all_tasks, available_nodes, link_metrics)
        if not upgrades:
            break
        # Process upgrades...
        cascade_round += 1
        
    utility_after = compute_swarm_utility_with_changes(all_tasks, tier_changes, abandoned)
    
    plan = DegradationPlan(
        trigger=trigger,
        affected_tasks=[t.id for t in affected_tasks],
        tier_changes=tier_changes,
        new_assignments=new_assignments,
        abandoned_tasks=abandoned,
        freed_nodes=[],
        utility_before=utility_before,
        utility_after=utility_after,
        decision_trace=trace
    )
    
    return plan
