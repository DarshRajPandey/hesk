"""Scenario generation: heterogeneous fleet, tiered mission, fault schedule.

The fleet and mission are drawn from a fixed catalogue so results are
interpretable: a few rare, high-value platforms (thermal, lidar, edge GPU)
among many cheap scouts. That rarity is exactly what makes allocation
order matter and is the regime HESK's scarcity term was designed for.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple

from hesk.core.types import DimType, PriorityClass
from hesk.tasks.model import DegradationTier, TaskDefinition, TaskRequirement

# ── Capability dimensions ────────────────────────────────────────────
DIMS: Dict[str, DimType] = {
    "sensing_visual": DimType.CONTINUOUS,
    "has_thermal": DimType.BOOLEAN,
    "has_lidar": DimType.BOOLEAN,
    "compute": DimType.CAPACITY,      # TFLOPS available
    "comm_bw": DimType.CAPACITY,      # Mbps uplink
    "runtime": DimType.CATEGORICAL,
}

# name: (fleet share, base capabilities)
ARCHETYPES: Dict[str, Tuple[float, dict]] = {
    "scout":   (0.40, dict(sensing_visual=0.62, has_thermal=False, has_lidar=False, compute=1.0, comm_bw=2.0, runtime="tflite")),
    "eo":      (0.22, dict(sensing_visual=0.90, has_thermal=False, has_lidar=False, compute=4.0, comm_bw=5.0, runtime="onnx")),
    "thermal": (0.10, dict(sensing_visual=0.80, has_thermal=True, has_lidar=False, compute=4.0, comm_bw=5.0, runtime="onnx")),
    "lidar":   (0.10, dict(sensing_visual=0.60, has_thermal=False, has_lidar=True, compute=2.0, comm_bw=5.0, runtime="onnx")),
    "gpu":     (0.10, dict(sensing_visual=0.50, has_thermal=False, has_lidar=False, compute=16.0, comm_bw=20.0, runtime="tensorrt")),
    "relay":   (0.08, dict(sensing_visual=0.40, has_thermal=False, has_lidar=False, compute=1.0, comm_bw=50.0, runtime="tflite")),
}


def _r(dim: str, **kw) -> TaskRequirement:
    return TaskRequirement(dim_type=DIMS[dim], **kw)


def _tiers(*specs) -> List[DegradationTier]:
    return [DegradationTier(tier_level=i, quality_estimate=q, required=req) for i, (q, req) in enumerate(specs)]


# name: (priority class, mission priority, tiers[(quality, required)])
TASK_TEMPLATES = {
    "sar_thermal": (PriorityClass.CRITICAL, 1.0, [
        (1.00, {"has_thermal": _r("has_thermal", value=True), "compute": _r("compute", threshold=4.0)}),
        (0.70, {"has_thermal": _r("has_thermal", value=True)}),
        (0.35, {"sensing_visual": _r("sensing_visual", threshold=0.85)}),
    ]),
    "mapping": (PriorityClass.IMPORTANT, 0.7, [
        (1.00, {"has_lidar": _r("has_lidar", value=True), "compute": _r("compute", threshold=8.0)}),
        (0.65, {"has_lidar": _r("has_lidar", value=True)}),
        (0.30, {"sensing_visual": _r("sensing_visual", threshold=0.80)}),
    ]),
    "detection": (PriorityClass.IMPORTANT, 0.6, [
        (1.00, {"sensing_visual": _r("sensing_visual", threshold=0.85), "compute": _r("compute", threshold=12.0)}),
        (0.65, {"sensing_visual": _r("sensing_visual", threshold=0.85)}),
        (0.35, {"sensing_visual": _r("sensing_visual", threshold=0.55)}),
    ]),
    "relay": (PriorityClass.IMPORTANT, 0.5, [
        (1.00, {"comm_bw": _r("comm_bw", threshold=20.0)}),
        (0.50, {"comm_bw": _r("comm_bw", threshold=4.0)}),
    ]),
    "patrol": (PriorityClass.OPTIONAL, 0.3, [
        (1.00, {"sensing_visual": _r("sensing_visual", threshold=0.50)}),
    ]),
}

# Mission mix per 24 nodes: (template, count at t=0, count arriving later)
MISSION_MIX = [("sar_thermal", 1, 2), ("mapping", 1, 1), ("detection", 2, 1),
               ("relay", 1, 1), ("patrol", 5, 3)]


@dataclass
class ScenarioConfig:
    n_nodes: int = 24
    task_scale: float = 1.0          # multiplies MISSION_MIX counts (scaled with n_nodes/24)
    duration: float = 600.0
    arena: float = 1000.0
    speed: float = 15.0              # m/s
    station_radius: float = 25.0
    # network
    loss: float = 0.0
    burst_len: float = 1.0           # >1 → bursty (Gilbert-Elliott) loss
    latency: float = 0.02            # seconds, base one-way
    jitter: float = 0.01
    jam: Optional[Tuple[float, float, float]] = None
    # faults
    kill_frac: float = 0.0
    kill_mode: str = "random"        # random | scarce | leader | busy
    kill_window: Tuple[float, float] = (120.0, 360.0)
    partitions: List[Tuple[float, float, int]] = field(default_factory=list)  # (t0, t1, k groups)
    partition_mode: str = "random"   # random | spatial
    n_degrade: int = 0               # sensor/compute degradation events
    degrade_window: Tuple[float, float] = (120.0, 360.0)

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class SimTask:
    defn: TaskDefinition
    template: str
    pos: Tuple[float, float]
    arrival: float

    @property
    def id(self) -> str:
        return self.defn.task_id


@dataclass
class NodeSpec:
    node_id: str
    archetype: str
    caps: dict
    pos: Tuple[float, float]


def make_task(task_id: str, template: str) -> TaskDefinition:
    pclass, prio, tiers = TASK_TEMPLATES[template]
    tiers_ = _tiers(*tiers)
    return TaskDefinition(task_id=task_id, priority_class=pclass, mission_priority=prio,
                          q_min=tiers_[-1].quality_estimate, tiers=tiers_)


def generate(cfg: ScenarioConfig, rng: random.Random) -> Tuple[List[NodeSpec], List[SimTask]]:
    # Fleet: deterministic proportional allocation (largest remainder), random positions.
    shares = {k: v[0] for k, v in ARCHETYPES.items()}
    raw = {k: s * cfg.n_nodes for k, s in shares.items()}
    counts = {k: max(1, int(math.floor(v))) for k, v in raw.items()}
    while sum(counts.values()) < cfg.n_nodes:
        k = max(raw, key=lambda a: raw[a] - counts[a])
        counts[k] += 1
    while sum(counts.values()) > cfg.n_nodes:
        k = max(counts, key=lambda a: counts[a])
        counts[k] -= 1
    kinds = [k for k, c in counts.items() for _ in range(c)]
    rng.shuffle(kinds)
    nodes = []
    width = len(str(cfg.n_nodes))
    base = (cfg.arena * 0.1, cfg.arena * 0.1)
    for i, kind in enumerate(kinds):
        caps = dict(ARCHETYPES[kind][1])
        caps["sensing_visual"] = round(min(1.0, max(0.0, caps["sensing_visual"] + rng.uniform(-0.04, 0.04))), 3)
        caps["compute"] = round(caps["compute"] * rng.uniform(0.9, 1.1), 2)
        pos = (base[0] + rng.uniform(0, 100), base[1] + rng.uniform(0, 100))  # launch area
        nodes.append(NodeSpec(f"n{i:0{width}d}", kind, caps, pos))

    scale = cfg.task_scale * cfg.n_nodes / 24.0
    tasks: List[SimTask] = []
    k = 0
    for template, n0, n1 in MISSION_MIX:
        for j in range(max(1, round(n0 * scale)) + round(n1 * scale)):
            arrival = 0.0 if j < max(1, round(n0 * scale)) else rng.uniform(60.0, cfg.duration * 0.6)
            pos = (rng.uniform(0.2, 1.0) * cfg.arena, rng.uniform(0.2, 1.0) * cfg.arena)
            tasks.append(SimTask(make_task(f"t{k:03d}", template), template, pos, round(arrival, 2)))
            k += 1
    return nodes, tasks
