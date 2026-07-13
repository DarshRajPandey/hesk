from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Set, Any, Optional

from hesk.core.types import DimType, NodeId
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskRequirement

class CompositionSemantic(Enum):
    MAX = "MAX"
    SUM_DIVISIBLE = "SUM_DIVISIBLE"
    NON_COMPOSABLE = "NON_COMPOSABLE"
    UNION = "UNION"

class CoalitionStatus(Enum):
    FORMING = "FORMING"
    ACTIVE = "ACTIVE"
    DEGRADED = "DEGRADED"
    DISSOLVED = "DISSOLVED"

@dataclass
class ComposedCapabilityState:
    members: List[NodeId]
    composed_values: Dict[str, Any]
    provider_map: Dict[str, NodeId]

@dataclass
class DataFlowLink:
    source_node: NodeId
    sink_node: NodeId
    required_bw_kbps: float
    available_bw_kbps: float
    latency_ms: float
    feasible: bool

@dataclass
class Coalition:
    coalition_id: str
    task_id: str
    members: List[NodeId]
    initiator: NodeId
    role_assignment: Dict[str, NodeId]  # dimension -> provider node ID
    composed_state: ComposedCapabilityState
    data_flow_plan: List[DataFlowLink]
    estimated_cost: float
    formation_time: float
    status: CoalitionStatus = CoalitionStatus.FORMING

@dataclass
class CoalitionResult:
    success: bool
    coalition: Optional[Coalition] = None
    rejection_reason: Optional[str] = None
    candidates_tried: int = 0
    best_partial: Optional[Dict[str, Any]] = None
