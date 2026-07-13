import math
from typing import Dict, List, Any, Union

from hesk.core.types import DimType
from hesk.capabilities.model import CapabilityState
from hesk.tasks.model import TaskRequirement
from hesk.capabilities.matching_model import CompResult, DimensionResult, MatchResult

# ─── Configuration ───────────────────────────────────────────────────
DEFAULT_T_HALF = 30.0    # staleness half-life (seconds)
DEFAULT_CONFIDENCE_FLOOR = 0.05  # below this, report is treated as UNKNOWN
DEFAULT_SURPLUS_CAP = 1.0     # max normalized surplus per dimension
DEFAULT_W_SAT = 0.8     # weight given to meeting the threshold
DEFAULT_W_HEAD = 0.2     # weight given to headroom (surplus)

# ─── Type-aware comparison dispatch ──────────────────────────────────

def compare_boolean(has: bool, required: bool) -> CompResult:
    return CompResult(met=(has is True or required is False))

def compare_continuous(value: float, threshold: float) -> CompResult:
    met = (value >= threshold)
    surplus = max(value - threshold, 0.0)
    return CompResult(met=met, surplus=surplus)

def compare_capacity(value: float, threshold: float) -> CompResult:
    met = (value >= threshold)
    surplus = max(value - threshold, 0.0)
    return CompResult(met=met, surplus=surplus)

def compare_categorical(value: Any, required_set: set) -> CompResult:
    compatible = (value in required_set)
    return CompResult(met=compatible, compatible=compatible)

def compare(node_value: Any, task_req: TaskRequirement) -> CompResult:
    """Dispatch to type-specific comparison based on dimension type tag."""
    if task_req.dim_type == DimType.BOOLEAN:
        return compare_boolean(node_value, task_req.value)
    elif task_req.dim_type == DimType.CONTINUOUS:
        return compare_continuous(node_value, task_req.threshold)
    elif task_req.dim_type == DimType.CAPACITY:
        return compare_capacity(node_value, task_req.threshold)
    elif task_req.dim_type == DimType.CATEGORICAL:
        return compare_categorical(node_value, task_req.required_set)
    else:
        raise ValueError(f"Unknown DimType: {task_req.dim_type}")

# ─── Staleness ───────────────────────────────────────────────────────

def compute_confidence(age_s: float, t_half: float = DEFAULT_T_HALF, confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR) -> float:
    if age_s <= 0.0:
        return 1.0
    raw = math.exp(-age_s / t_half)
    if raw < confidence_floor:
        return 0.0
    return raw

# ─── Phase 1: Eligibility ───────────────────────────────────────────

def check_eligibility(c_i: CapabilityState, r_req: Dict[str, TaskRequirement]) -> bool:
    """Return True iff C_i meets ALL required dimensions."""
    for d, req in r_req.items():
        node_val = c_i.get_dimension(d)
        if node_val is None:
            return False  # Missing → does not have
            
        result = compare(node_val, req)
        if not result.met:
            return False  # Below threshold
            
    return True

# ─── Phase 2: Quality ───────────────────────────────────────────────

def compute_match_quality(
    c_i: CapabilityState, 
    r_pref: Dict[str, TaskRequirement],
    w_sat: float = DEFAULT_W_SAT,
    w_head: float = DEFAULT_W_HEAD,
    surplus_cap: float = DEFAULT_SURPLUS_CAP
) -> float:
    """Compute quality score over preferred dimensions."""
    if not r_pref:
        return 1.0  # No preferences → perfect match
        
    total = 0.0
    for d, pref in r_pref.items():
        node_val = c_i.get_dimension(d)
        if node_val is None:
            score_d = 0.0
        else:
            result = compare(node_val, pref)
            if pref.dim_type in (DimType.BOOLEAN, DimType.CATEGORICAL):
                score_d = 1.0 if result.met else 0.0
            else:
                satisfaction = 1.0 if result.met else 0.0
                if pref.threshold == 0.0:
                    headroom = 0.0
                else:
                    headroom = min(result.surplus / pref.threshold, surplus_cap)
                score_d = (w_sat * satisfaction) + (w_head * headroom)
        total += score_d
        
    quality = total / len(r_pref)
    return max(0.0, min(1.0, quality))  # Clamp between 0.0 and 1.0

# ─── Full match ──────────────────────────────────────────────────────

def compute_full_match(
    c_i: CapabilityState, 
    r_j_required: Dict[str, TaskRequirement], 
    r_j_preferred: Dict[str, TaskRequirement], 
    age_s: float = 0.0,
    t_half: float = DEFAULT_T_HALF,
    confidence_floor: float = DEFAULT_CONFIDENCE_FLOOR,
    w_sat: float = DEFAULT_W_SAT,
    w_head: float = DEFAULT_W_HEAD,
    surplus_cap: float = DEFAULT_SURPLUS_CAP
) -> MatchResult:
    """
    Main entry point.
    Returns MatchResult with eligibility, quality, confidence,
    per-dimension details, and diagnostic lists.
    """
    confidence = compute_confidence(age_s, t_half, confidence_floor)
    
    if confidence == 0.0:
        return MatchResult(
            eligible=False, 
            quality=0.0, 
            confidence=0.0,
            weighted_quality=0.0, 
            dimension_details={},
            unmet_required=list(r_j_required.keys()),
            missing_dimensions=list(r_j_required.keys())
        )
        
    # Phase 1
    eligible = check_eligibility(c_i, r_j_required)
    
    # Dimension details
    details: Dict[str, DimensionResult] = {}
    unmet_req: List[str] = []
    missing: List[str] = []
    
    all_dims = set(r_j_required.keys()).union(set(r_j_preferred.keys()))
    
    for d in all_dims:
        is_required = (d in r_j_required)
        task_spec = r_j_required[d] if is_required else r_j_preferred[d]
        node_val = c_i.get_dimension(d)
        
        if node_val is None:
            missing.append(d)
            details[d] = DimensionResult(
                dimension=d, 
                dim_type=task_spec.dim_type,
                required=is_required, 
                met=False,
                surplus=0.0, 
                node_value=None,
                task_value=task_spec, 
                compatible=False
            )
            if is_required:
                unmet_req.append(d)
        else:
            result = compare(node_val, task_spec)
            details[d] = DimensionResult(
                dimension=d, 
                dim_type=task_spec.dim_type,
                required=is_required, 
                met=result.met,
                surplus=result.surplus,
                node_value=node_val, 
                task_value=task_spec,
                compatible=result.compatible if hasattr(result, 'compatible') else result.met
            )
            if is_required and not result.met:
                unmet_req.append(d)
                
    # Phase 2
    quality = 0.0
    if eligible:
        quality = compute_match_quality(c_i, r_j_preferred, w_sat, w_head, surplus_cap)
        
    weighted_quality = quality * confidence
    
    return MatchResult(
        eligible=eligible,
        quality=quality,
        confidence=confidence,
        weighted_quality=weighted_quality,
        dimension_details=details,
        unmet_required=unmet_req,
        missing_dimensions=missing
    )
