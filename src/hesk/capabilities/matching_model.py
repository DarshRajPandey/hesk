from dataclasses import dataclass, field
from typing import Dict, List, Any, Optional
from hesk.core.types import DimType

@dataclass
class CompResult:
    """Result of a single capability dimension comparison."""
    met: bool
    surplus: float = 0.0
    compatible: bool = False

@dataclass
class DimensionResult:
    """Detailed result of comparing a node's capability dimension against a task requirement."""
    dimension: str
    dim_type: DimType
    required: bool
    met: bool
    surplus: float
    node_value: Any
    task_value: Any
    compatible: bool

@dataclass
class MatchResult:
    """The structured output of a full match operation for a single node against a task."""
    eligible: bool
    quality: float
    confidence: float
    weighted_quality: float
    
    # Per-dimension detail
    dimension_details: Dict[str, DimensionResult] = field(default_factory=dict)
    
    # Summary flags
    unmet_required: List[str] = field(default_factory=list)
    missing_dimensions: List[str] = field(default_factory=list)
