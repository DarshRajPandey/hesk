from enum import Enum, auto

class DimType(Enum):
    """
    Semantic dimension types for capabilities, dictating matching and aggregation behavior.
    """
    BOOLEAN = auto()       # Either present or not (e.g., has_camera)
    CONTINUOUS = auto()    # Scalar precision (e.g., sensing_visual=0.91), capped at 1.0
    CAPACITY = auto()      # Additive magnitude (e.g., compute_flops=8.0)
    CATEGORICAL = auto()   # String enumeration (e.g., model_runtime="tensorrt")

class PriorityClass(Enum):
    """
    Mission priority classes dictating degradation behavior.
    """
    CRITICAL = auto()      # Degrade last. Never operate below q_min.
    IMPORTANT = auto()     # Degrade before CRITICAL. May operate at lowest tier.
    OPTIONAL = auto()      # Degrade first. May be abandoned freely.

# Type aliases for strong domain semantics
NodeId = str
TaskId = str
EventId = str
