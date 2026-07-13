import uuid
import time
from typing import Dict, List, Set, Any, Optional

from hesk.core.types import DimType, NodeId
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskDefinition, TaskRequirement
from hesk.capabilities.matching import check_eligibility, compare

from hesk.coalitions.model import (
    CompositionSemantic,
    CoalitionStatus,
    ComposedCapabilityState,
    DataFlowLink,
    Coalition,
    CoalitionResult
)

# Configuration defaults
CAPACITY_OVERHEAD_FRACTION = 0.05
C_COORD = 0.1
C_FRAG = 0.15
INFINITY = float('inf')

class LinkMetrics:
    """Mock interface for getting link quality between nodes."""
    def get_bandwidth(self, source: str, sink: str) -> float:
        return INFINITY
        
    def get_latency(self, source: str, sink: str) -> float:
        return 0.0

def dimension_composition_semantic(dim_type: DimType, dimension_name: str) -> CompositionSemantic:
    """Determine how a capability dimension composes based on its type."""
    if dim_type == DimType.BOOLEAN:
        return CompositionSemantic.MAX
    elif dim_type == DimType.CONTINUOUS:
        return CompositionSemantic.MAX
    elif dim_type == DimType.CAPACITY:
        return CompositionSemantic.SUM_DIVISIBLE
    elif dim_type == DimType.CATEGORICAL:
        return CompositionSemantic.UNION
    return CompositionSemantic.NON_COMPOSABLE

def dimension_meets_threshold(node_val: Any, req: TaskRequirement) -> bool:
    """Check if a single dimension meets a requirement."""
    if node_val is None:
        return False
    result = compare(node_val, req)
    return result.met

def avg_inverse_bandwidth(node: CapabilityState, members: List[CapabilityState], metrics: LinkMetrics) -> float:
    """Compute average inverse bandwidth from node to existing coalition members."""
    total_inv = 0.0
    valid_links = 0
    for m in members:
        bw = metrics.get_bandwidth(node.node_id, m.node_id)
        if bw > 0:
            total_inv += 1.0 / bw
            valid_links += 1
    
    if valid_links == 0:
        return INFINITY
    return total_inv / valid_links

def compose_capabilities(
    members: List[CapabilityState], 
    required_dims: Dict[str, TaskRequirement]
) -> ComposedCapabilityState:
    """Apply type-dependent composition rules to produce ComposedCapabilityState."""
    composed = {}
    providers = {}
    
    for d, req in required_dims.items():
        semantic = dimension_composition_semantic(req.dim_type, d)
        
        if semantic == CompositionSemantic.MAX:
            # Need to find the maximum value among members that have the dimension
            valid_members = [m for m in members if m.get_dimension(d) is not None]
            if not valid_members:
                continue
                
            best_member = max(valid_members, key=lambda m: float(m.get_dimension(d)))
            composed[d] = best_member.get_dimension(d)
            providers[d] = best_member.node_id
            
        elif semantic == CompositionSemantic.SUM_DIVISIBLE:
            valid_members = [m for m in members if m.get_dimension(d) is not None]
            if not valid_members:
                continue
                
            raw_sum = sum(float(m.get_dimension(d)) for m in valid_members)
            overhead = CAPACITY_OVERHEAD_FRACTION * len(members)
            composed[d] = raw_sum * (1.0 - overhead)
            
            best_member = max(valid_members, key=lambda m: float(m.get_dimension(d)))
            providers[d] = best_member.node_id
            
        elif semantic == CompositionSemantic.NON_COMPOSABLE:
            valid_members = [m for m in members if m.get_dimension(d) is not None]
            capable = [m for m in valid_members if dimension_meets_threshold(m.get_dimension(d), req)]
            if capable:
                best_member = max(capable, key=lambda m: float(m.get_dimension(d)))
                composed[d] = best_member.get_dimension(d)
                providers[d] = best_member.node_id
                
        elif semantic == CompositionSemantic.UNION:
            combined_set = set()
            valid_members = [m for m in members if m.get_dimension(d) is not None]
            for m in valid_members:
                val = m.get_dimension(d)
                if isinstance(val, str):
                    combined_set.add(val)
                elif isinstance(val, (list, set)):
                    combined_set.update(val)
            composed[d] = combined_set
            
            # Provider is first member whose value matches requirement
            for m in valid_members:
                if dimension_meets_threshold(m.get_dimension(d), req):
                    providers[d] = m.node_id
                    break
                    
    # Ensure provider_map and composed_values only contain dimensions that have a provider
    return ComposedCapabilityState(
        members=[m.node_id for m in members],
        composed_values={k: v for k, v in composed.items() if k in providers},
        provider_map=providers
    )

def estimate_coalition_cost(
    members: List[CapabilityState], 
    task: TaskDefinition, 
    data_flow_plan: List[DataFlowLink]
) -> float:
    """Estimate total cost of coalition execution."""
    
    # Placeholder for per-member execution cost
    # In a full implementation, we'd calculate this based on energy consumption for the role
    exec_cost = 0.8  # Using 0.8 as in the worked example
    
    # Data transfer cost
    transfer_cost = 0.0
    for flow in data_flow_plan:
        if flow.source_node != flow.sink_node and flow.available_bw_kbps > 0 and flow.available_bw_kbps != INFINITY:
            # Assuming duration = 60s for the estimate as in the example
            duration_s = 60.0 
            transfer_cost += (flow.required_bw_kbps * duration_s) / flow.available_bw_kbps
    
    # Coordination overhead
    coord_cost = C_COORD * len(members)
    
    # Fragility penalty
    frag_cost = C_FRAG * (len(members) - 1)
    
    return exec_cost + transfer_cost + coord_cost + frag_cost

def form_coalition(
    task_id: str,
    required: Dict[str, TaskRequirement],
    data_flows: List[Any], # List of dicts or objects representing DataFlowRequirements
    candidates: List[CapabilityState], 
    link_metrics: LinkMetrics, 
    initiator_id: str,
    k_max: int = 4
) -> CoalitionResult:
    """
    Attempt to form a coalition for task from candidates.
    Returns CoalitionResult.
    """
    gap_set = set(required.keys())
    coalition_members: List[CapabilityState] = []
    
    # Phase 1: Greedy incremental construction
    available = list(candidates)
    
    while gap_set and len(coalition_members) < k_max and available:
        best_score = -1.0
        best_candidate = None
        
        current_composed = compose_capabilities(coalition_members, required) if coalition_members else None
        
        for n_k in available:
            gaps_filled = 0.0
            
            temp_members = coalition_members + [n_k]
            temp_composed = compose_capabilities(temp_members, required)
            
            for d in gap_set:
                val = temp_composed.composed_values.get(d)
                if dimension_meets_threshold(val, required[d]):
                    gaps_filled += 1.0
                else:
                    req = required[d]
                    if req.dim_type == DimType.CAPACITY:
                        old_val = current_composed.composed_values.get(d, 0.0) if current_composed else 0.0
                        new_val = val if val is not None else 0.0
                        if new_val > old_val and req.threshold and req.threshold > 0:
                            gaps_filled += min((new_val - old_val) / req.threshold, 0.99)
            
            if gaps_filled <= 0:
                continue
                
            if coalition_members:
                comm_cost = avg_inverse_bandwidth(n_k, coalition_members, link_metrics)
                if comm_cost == INFINITY:
                    continue
            else:
                comm_cost = 0.0
                
            score = gaps_filled / (1.0 + comm_cost)
            
            if score > best_score:
                best_score = score
                best_candidate = n_k
                
        if best_candidate is None:
            break
            
        coalition_members.append(best_candidate)
        available.remove(best_candidate)
        
        # Update gap set
        new_composed = compose_capabilities(coalition_members, required)
        for d in list(gap_set):
            if dimension_meets_threshold(new_composed.composed_values.get(d), required[d]):
                gap_set.discard(d)
                
    # Phase 2: Verification
    if gap_set:
        return CoalitionResult(
            success=False,
            rejection_reason=f"Cannot cover dimensions: {gap_set}",
            candidates_tried=len(candidates) - len(available),
            best_partial={"covered": set(required.keys()) - gap_set, "missing": gap_set}
        )
        
    composed_state = compose_capabilities(coalition_members, required)
    
    # Convert ComposedCapabilityState to a mock CapabilityState for eligibility check
    mock_c = CapabilityState(
        node_id="COALITION",
        timestamp=time.time(),
        dimensions=composed_state.composed_values
    )
    
    if not check_eligibility(mock_c, required):
        return CoalitionResult(
            success=False,
            rejection_reason="Composed state fails eligibility"
        )
        
    # Phase 3: Communication feasibility
    data_flow_plan = []
    
    for flow in data_flows:
        source_node = composed_state.provider_map.get(flow.source_capability)
        sink_node = composed_state.provider_map.get(flow.sink_capability)
        
        if source_node is None or sink_node is None:
            return CoalitionResult(
                success=False,
                rejection_reason=f"No provider for {flow.source_capability} or {flow.sink_capability}"
            )
            
        if source_node == sink_node:
            data_flow_plan.append(DataFlowLink(
                source_node=source_node, sink_node=sink_node,
                required_bw_kbps=flow.bandwidth_kbps,
                available_bw_kbps=INFINITY,
                latency_ms=0.0,
                feasible=True
            ))
            continue
            
        bw_available = link_metrics.get_bandwidth(source_node, sink_node)
        latency = link_metrics.get_latency(source_node, sink_node)
        
        bw_ok = bw_available >= flow.bandwidth_kbps
        lat_ok = (flow.max_latency_ms is None) or (latency <= flow.max_latency_ms)
        
        if not (bw_ok and lat_ok):
            return CoalitionResult(
                success=False,
                rejection_reason=f"Link {source_node}->{sink_node} infeasible"
            )
            
        data_flow_plan.append(DataFlowLink(
            source_node=source_node, sink_node=sink_node,
            required_bw_kbps=flow.bandwidth_kbps,
            available_bw_kbps=bw_available,
            latency_ms=latency,
            feasible=True
        ))
        
    # Phase 4: Cost estimation
    total_cost = estimate_coalition_cost(coalition_members, None, data_flow_plan)
    
    coalition = Coalition(
        coalition_id=str(uuid.uuid4()),
        task_id=task_id,
        members=[m.node_id for m in coalition_members],
        initiator=initiator_id,
        role_assignment=composed_state.provider_map,
        composed_state=composed_state,
        data_flow_plan=data_flow_plan,
        estimated_cost=total_cost,
        formation_time=time.time(),
        status=CoalitionStatus.FORMING
    )
    
    return CoalitionResult(success=True, coalition=coalition)
