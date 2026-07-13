from dataclasses import dataclass
from typing import Dict, Any
from hesk.core.types import NodeId, DimType

@dataclass(frozen=True)
class CapabilityDefinition:
    """Defines a capability dimension."""
    dimension: str
    dim_type: DimType

@dataclass(frozen=True)
class CapabilityState:
    """
    Intrinsic capability state of a node.
    Immutable representation of physical capability.
    """
    node_id: NodeId
    timestamp: float
    dimensions: Dict[str, Any]  # map of dimension -> value

    def get_dimension(self, dim: str) -> Any:
        return self.dimensions.get(dim)

@dataclass(frozen=True)
class LinkState:
    """
    Relational capability between two specific nodes (e.g., communication).
    """
    source_id: NodeId
    target_id: NodeId
    timestamp: float
    bandwidth_kbps: float
    latency_ms: float
    is_connected: bool
