import time
import pytest
import math

from hesk.core.types import DimType, PriorityClass
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskRequirement, TaskDefinition, DegradationTier, ActiveTask, TaskStatus
from hesk.capabilities.matching import compute_confidence
from hesk.coalitions.formation import form_coalition, LinkMetrics
from hesk.tasks.allocation import compute_scarcity_penalty
from hesk.degradation.logic import find_best_satisfaction_with_descent, AvailableNodes, SatisfactionAction
from hesk.degradation.model import DegradationTrigger

def test_staleness_half_life():
    """BUG-002: Staleness Half-Life Math Error"""
    t_half = 30.0
    age = 30.0
    confidence = compute_confidence(age, t_half)
    # Expected: 0.5 because 1 half-life has passed. 
    # Previously it was math.exp(-1) which is ~0.367
    assert math.isclose(confidence, 0.5, rel_tol=1e-5), f"Expected 0.5, got {confidence}"

def test_additive_capacity_coalition():
    """BUG-003: Additive Coalition Impossibility"""
    # Two nodes with VRAM 4. Task requires VRAM 6.
    req = {"vram": TaskRequirement(dim_type=DimType.CAPACITY, threshold=6.0)}
    
    n1 = CapabilityState(node_id="A", timestamp=0.0, dimensions={"vram": 4.0})
    n2 = CapabilityState(node_id="B", timestamp=0.0, dimensions={"vram": 4.0})
    
    result = form_coalition(
        task_id="task1",
        required=req,
        data_flows=[],
        candidates=[n1, n2],
        link_metrics=LinkMetrics(),
        initiator_id="local_node"
    )
    
    assert result.success is True, f"Failed to form additive coalition: {result.rejection_reason}"
    assert set(result.coalition.members) == {"A", "B"}, "Should include both members"

def test_scarcity_unit_scale_independence():
    """BUG-004: Scarcity Scale Dominance"""
    # Nodes have VRAM (raw units) and Camera (normalized)
    swarm = [
        CapabilityState(node_id="A", timestamp=0.0, dimensions={"vram": 4096.0, "camera": 0.8}),
        CapabilityState(node_id="B", timestamp=0.0, dimensions={"vram": 8192.0, "camera": 0.2}),
        CapabilityState(node_id="C", timestamp=0.0, dimensions={"vram": 2048.0, "camera": 0.5})
    ]
    
    # Target node has high VRAM (8192) but task only needs camera.
    # It should not get a 1.0 scarcity penalty just because 8192 >= 0.1
    target_node = swarm[1]
    reqs = {"camera"}
    
    # Penalty with dynamic scale
    penalty = compute_scarcity_penalty(target_node, reqs, swarm)
    
    # Scarcity of VRAM: 8192 is the max. 10% of max is 819.2.
    # Meaningful nodes: A(4096), B(8192), C(2048). All 3 are > 819.2.
    # So scarcity is 1.0 - (3/3) = 0.0
    # Penalty should be 0.0 because VRAM is ubiquitous.
    assert penalty == 0.0, f"Expected 0.0 penalty for ubiquitous resource, got {penalty}"

def test_solo_reassign_selects_lowest_system_cost():
    """Phase 8 BUG: find_best_satisfaction uses list order instead of system cost"""
    # Create two nodes. B is a better match (lower cost).
    # But A appears first in the list.
    req = {"compute": TaskRequirement(dim_type=DimType.CONTINUOUS, threshold=0.5)}
    
    n1 = CapabilityState(node_id="A", timestamp=0.0, dimensions={"compute": 0.51}) # Barely meets
    n2 = CapabilityState(node_id="B", timestamp=0.0, dimensions={"compute": 0.99}) # Excellent match
    
    available = AvailableNodes([n1, n2], DegradationTrigger(source_node="Z", trigger_type="failure"))
    
    task_def = TaskDefinition(
        task_id="t1",
        priority_class=PriorityClass.IMPORTANT,
        mission_priority=0.5,
        q_min=0.1,
        tiers=[DegradationTier(tier_level=0, quality_estimate=1.0, required=req, preferred=req)]
    )
    
    active_task = ActiveTask(task_def, 0, TaskStatus.EXECUTING)
    
    result = find_best_satisfaction_with_descent(active_task, available, LinkMetrics())
    
    assert result.action == SatisfactionAction.SOLO_REASSIGN
    # Should pick B because B has a much higher match quality (which means lower system cost)
    assert result.assignee == "B", f"Selected {result.assignee} instead of cost-optimal B"
