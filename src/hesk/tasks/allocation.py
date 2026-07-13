import math
from typing import List, Set, Optional

from hesk.core.types import NodeId
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import Bid, AllocationResult

def compute_scarcity(dimension: str, swarm: List[CapabilityState], theta: float = 0.1) -> float:
    """
    Compute scarcity of a dimension across the known swarm.
    Scarcity = 1.0 - (nodes_with_meaningful_cap / total_nodes)
    """
    if not swarm:
        return 1.0  # Assumed maximally scarce if no information is available

    count_meaningful = 0
    for node_state in swarm:
        # For simplicity in V1, we assume numeric capabilities mapped in the dimensions dict.
        val = node_state.get_dimension(dimension)
        
        if val is not None and isinstance(val, (int, float)):
            if val >= theta:
                count_meaningful += 1
        elif isinstance(val, bool) and val is True:
            # For boolean, any truthy value counts as meaningful
            count_meaningful += 1

    return 1.0 - (count_meaningful / len(swarm))

def compute_exec_cost(match_quality: float, energy: float) -> float:
    """
    Estimate execution cost. Higher quality reduces cost, lower energy increases cost.
    """
    energy_penalty = 1.0 - energy
    return (1.0 - match_quality) + energy_penalty

def compute_energy_cost(base_consumption: float, energy: float) -> float:
    """
    Compute proportional energy cost.
    """
    if energy <= 0.0:
        return float('inf')
    return base_consumption / energy

def compute_scarcity_penalty(
    own_state: CapabilityState, 
    required_dimensions: Set[str], 
    swarm: List[CapabilityState], 
    thetas: dict = None
) -> float:
    """
    Penalize the assignment if the node possesses scarce capabilities that are NOT required by the task.
    """
    if thetas is None:
        thetas = {}
        
    penalty = 0.0
    for dim, val in own_state.dimensions.items():
        if dim in required_dimensions:
            continue  # Productive use, no penalty
            
        theta = thetas.get(dim, 0.1)
        is_meaningful = False
        
        if isinstance(val, (int, float)) and val >= theta:
            is_meaningful = True
        elif isinstance(val, bool) and val is True:
            is_meaningful = True
            
        if is_meaningful:
            sigma = compute_scarcity(dim, swarm, theta)
            # The node has it, and it's scarce, but the task doesn't need it!
            # Penalty is proportional to how scarce it is (sigma).
            # We use an indicator function instead of raw multiplier.
            penalty += sigma
            
    return penalty

def compute_system_cost(
    match_quality: float,
    energy: float,
    base_consumption: float,
    scarcity_penalty: float,
    comm_cost: float = 0.0,
    w_exec: float = 1.0,
    w_energy: float = 0.5,
    w_scarcity: float = 2.0,
    w_comm: float = 0.0
) -> float:
    """
    Compute total system cost for assigning this node to the task.
    """
    exec_c = compute_exec_cost(match_quality, energy)
    ener_c = compute_energy_cost(base_consumption, energy)
    
    cost = (w_exec * exec_c) + (w_energy * ener_c) + (w_scarcity * scarcity_penalty) + (w_comm * comm_cost)
    return cost

def evaluate_bids(bids: List[Bid], task_id: str) -> AllocationResult:
    """
    Select the winning bid based on lowest system cost, tiebreaking on match_quality, energy, and node_id.
    """
    if not bids:
        return AllocationResult(
            task_id=task_id, 
            assigned_node=None, 
            system_cost=None, 
            match_quality=None,
            bids_received=0
        )
        
    # Sort criteria: 
    # 1. System cost (ascending)
    # 2. Match quality (descending -> negative for sort)
    # 3. Energy (descending -> negative for sort)
    # 4. Node ID (ascending)
    def sort_key(b: Bid):
        return (
            b.system_cost,
            -b.match_quality,
            -b.energy,
            b.node_id
        )
        
    sorted_bids = sorted(bids, key=sort_key)
    winner = sorted_bids[0]
    runner_up = sorted_bids[1] if len(sorted_bids) > 1 else None
    
    return AllocationResult(
        task_id=task_id,
        assigned_node=winner.node_id,
        system_cost=winner.system_cost,
        match_quality=winner.match_quality,
        runner_up_node=runner_up.node_id if runner_up else None,
        runner_up_cost=runner_up.system_cost if runner_up else None,
        bids_received=len(bids)
    )
