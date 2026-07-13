from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional, Any, Union
from hesk.core.types import TaskId, NodeId, DimType, PriorityClass
from hesk.capabilities.model import CapabilityState

@dataclass(frozen=True)
class TaskRequirement:
    """Specifies a requirement for a specific dimension."""
    dim_type: DimType
    value: Optional[bool] = None          # For BOOLEAN
    threshold: Optional[float] = None     # For CONTINUOUS or CAPACITY
    required_set: Optional[Set[str]] = None  # For CATEGORICAL

    def __post_init__(self):
        if self.dim_type == DimType.BOOLEAN and self.value is None:
            raise ValueError("BOOLEAN requirement must specify 'value'")
        if self.dim_type in (DimType.CONTINUOUS, DimType.CAPACITY) and self.threshold is None:
            raise ValueError("CONTINUOUS/CAPACITY requirement must specify 'threshold'")
        if self.dim_type == DimType.CATEGORICAL and self.required_set is None:
            raise ValueError("CATEGORICAL requirement must specify 'required_set'")

@dataclass(frozen=True)
class DataFlowRequirement:
    """Specifies data flow dependency within a coalition."""
    source_capability: str
    sink_capability: str
    bandwidth_kbps: float
    max_latency_ms: Optional[float] = None

@dataclass(frozen=True)
class DegradationTier:
    """A specific quality level at which a task can be executed."""
    tier_level: int
    quality_estimate: float
    required: Dict[str, TaskRequirement]
    preferred: Dict[str, TaskRequirement] = field(default_factory=dict)
    data_flow: List[DataFlowRequirement] = field(default_factory=list)

    def __post_init__(self):
        if not (0.0 <= self.quality_estimate <= 1.0):
            raise ValueError("quality_estimate must be between 0.0 and 1.0")

@dataclass(frozen=True)
class TaskDefinition:
    """Mission task with multiple degradation tiers."""
    task_id: TaskId
    priority_class: PriorityClass
    mission_priority: float  # (0, 1]
    q_min: float  # minimum acceptable quality
    tiers: List[DegradationTier]

    def __post_init__(self):
        if not (0.0 < self.mission_priority <= 1.0):
            raise ValueError("mission_priority must be in (0, 1]")
        if not (0.0 <= self.q_min <= 1.0):
            raise ValueError("q_min must be in [0, 1]")
        
        # Verify tier ordering: T_0 must have highest quality, T_n must have lowest
        if not self.tiers:
            raise ValueError("Task must have at least one DegradationTier")
            
        expected_level = 0
        prev_quality = 1.000001
        for tier in self.tiers:
            if tier.tier_level != expected_level:
                raise ValueError(f"Tiers must be contiguous starting from 0. Expected {expected_level}, got {tier.tier_level}")
            if tier.quality_estimate >= prev_quality:
                raise ValueError(f"Tier {tier.tier_level} quality ({tier.quality_estimate}) must be strictly less than previous tier's quality ({prev_quality})")
            if tier.quality_estimate < self.q_min:
                raise ValueError(f"Tier {tier.tier_level} quality ({tier.quality_estimate}) is below minimum acceptable quality ({self.q_min})")
            expected_level += 1
            prev_quality = tier.quality_estimate

@dataclass
class Bid:
    """
    A bid submitted by an eligible node during the bidding process.
    """
    task_id: TaskId
    node_id: NodeId
    system_cost: float
    match_quality: float
    energy: float
    cap_snapshot: CapabilityState

@dataclass
class AllocationResult:
    """
    The output of the evaluate_bids algorithm.
    """
    task_id: TaskId
    assigned_node: Optional[NodeId]
    system_cost: Optional[float]
    match_quality: Optional[float]
    runner_up_node: Optional[NodeId] = None
    runner_up_cost: Optional[float] = None
    bids_received: int = 0
    bids_expected: int = 0

class TaskStatus:
    EXECUTING = "EXECUTING"
    DEGRADED = "DEGRADED"
    ABANDONED = "ABANDONED"
    COMPLETED = "COMPLETED"

class ActiveTask:
    """Runtime representation of a task being executed."""
    def __init__(self, task_def: TaskDefinition, current_tier: int, status: str, assignee: Union[NodeId, 'Coalition', None] = None):
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
