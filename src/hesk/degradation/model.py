from enum import Enum
from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional, Tuple, Union

from hesk.core.types import NodeId
from hesk.coalitions.model import Coalition

class DegradationTriggerType(Enum):
    NODE_LOSS = "NODE_LOSS"
    CAPABILITY_DEGRADATION = "CAPABILITY_DEGRADATION"
    LINK_LOSS = "LINK_LOSS"
    ENERGY_CRITICAL = "ENERGY_CRITICAL"
    COALITION_MEMBER_LOST = "COALITION_MEMBER_LOST"

class MissionPriorityClass(Enum):
    CRITICAL = "CRITICAL"    # 0.8 to 1.0
    IMPORTANT = "IMPORTANT"  # 0.4 to 0.79
    OPTIONAL = "OPTIONAL"    # 0.0 to 0.39

class TraceAction(Enum):
    REASSIGN = "REASSIGN"
    DEGRADE = "DEGRADE"
    ABANDON = "ABANDON"
    UPGRADE = "UPGRADE"
    SKIP = "SKIP"
    ALARM = "ALARM"

class SatisfactionAction(Enum):
    SOLO_REASSIGN = "SOLO_REASSIGN"
    COALITION_FORM = "COALITION_FORM"
    TIER_DESCENT = "TIER_DESCENT"
    ABANDON = "ABANDON"

@dataclass
class DegradationTrigger:
    trigger_type: DegradationTriggerType
    source_node: NodeId
    details: Dict[str, Any] = field(default_factory=dict)

@dataclass
class TraceEntry:
    timestamp: float
    task_id: str
    action: TraceAction
    reason: str
    old_tier: Optional[int] = None
    new_tier: Optional[int] = None
    old_assignee: Union[NodeId, Coalition, None] = None
    new_assignee: Union[NodeId, Coalition, None] = None
    quality_change: Optional[Tuple[float, float]] = None

@dataclass
class DegradationPlan:
    trigger: DegradationTrigger
    affected_tasks: List[str]
    tier_changes: Dict[str, Tuple[Optional[int], Optional[int]]]
    new_assignments: Dict[str, Union[NodeId, Coalition]]
    abandoned_tasks: List[str]
    freed_nodes: List[NodeId] = field(default_factory=list)
    utility_before: float = 0.0
    utility_after: float = 0.0
    decision_trace: List[TraceEntry] = field(default_factory=list)

@dataclass
class ResponsibilitySuccession:
    lost_node: NodeId
    lost_responsibilities: List[str]
    successors: Dict[str, Union[NodeId, Coalition, str]]  # str="ABANDONED"
    succession_type: Dict[str, SatisfactionAction]

@dataclass
class SatisfactionResult:
    action: SatisfactionAction
    assignee: Optional[NodeId] = None
    coalition: Optional[Coalition] = None
    tier: Any = None # Any tier object
    best_partial: Optional[Dict[str, Any]] = None
