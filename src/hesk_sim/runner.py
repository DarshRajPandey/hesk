"""One run = pure function of (scenario config, algorithm, seed)."""
from __future__ import annotations

import hashlib
import json
import platform
from dataclasses import fields
from typing import Dict

from hesk_sim.agents.base import AgentConfig
from hesk_sim.agents.cbba import CBBAAgent
from hesk_sim.agents.centralized import CentralAgent, OracleAgent, OracleBrain
from hesk_sim.agents.hesk_agent import HeskAgent
from hesk_sim.agents.independent import IndependentAgent
from hesk_sim.engine import derive_seed
from hesk_sim.scenario import ScenarioConfig
from hesk_sim.world import World

# name -> (agent class, flags).
#   hesk  — the kernel exactly as specified in docs/algorithms (Algs 001-008).
#   hesk2 — + scarcity-aware coalition recruitment       (Finding 1)
#   hesk3 — + lease-based ownership & indirect liveness   (Findings 2-3)
# Ablations remove one component at a time from hesk3.
H2 = {"coalition_scarcity": True}
H3 = {**H2, "lease": True}
ALGORITHMS: Dict[str, tuple] = {
    "hesk":             (HeskAgent, {}),
    "hesk2":            (HeskAgent, H2),
    "hesk3":            (HeskAgent, H3),
    "hesk4":            (HeskAgent, {**H3, "claims": True}),
    "hesk5":            (HeskAgent, {**H3, "claims": "adaptive"}),
    "cbba":             (CBBAAgent, {}),
    "central":          (CentralAgent, {"quorum": True}),
    "central_noquorum": (CentralAgent, {"quorum": False}),
    "cnp":              (HeskAgent, {"scarcity": False, "coalitions": False, "upgrade": False,
                                     "gossip": False, "reconcile": "lww"}),
    "oracle":           (OracleAgent, {}),
    "independent":      (IndependentAgent, {}),
    # ── ablations of hesk3 ──
    "abl-lease":        (HeskAgent, {**H3, "lease": False}),
    "abl-coalscarcity": (HeskAgent, {**H3, "coalition_scarcity": False}),
    "abl-scarcity":     (HeskAgent, {**H3, "scarcity": False}),
    "abl-tiers":        (HeskAgent, {**H3, "tiers": False}),
    "abl-coalitions":   (HeskAgent, {**H3, "coalitions": False}),
    "abl-upgrade":      (HeskAgent, {**H3, "upgrade": False}),
    "abl-gossip":       (HeskAgent, {**H3, "gossip": False}),
    "abl-reconcile":    (HeskAgent, {**H3, "reconcile": "none"}),
    "abl-lww":          (HeskAgent, {**H3, "reconcile": "lww"}),
    "abl-raw008":       (HeskAgent, {**H3, "reconcile": "kernel"}),
}


def config_hash(d: dict) -> str:
    return hashlib.sha256(json.dumps(d, sort_keys=True, default=str).encode()).hexdigest()[:12]


def run_one(scenario: dict, algo: str, seed: int, agent_overrides: dict | None = None,
            keep_timeline: bool = False) -> dict:
    valid = {f.name for f in fields(ScenarioConfig)}
    sc = ScenarioConfig(**{k: (tuple(v) if k in ("kill_window", "degrade_window", "jam") and v is not None else v)
                           for k, v in scenario.items() if k in valid})
    cls, flags = ALGORITHMS[algo]
    overrides = dict(agent_overrides or {})
    world = World(sc, seed)
    acfg = AgentConfig(name=algo, hb=overrides.pop("hb", 1.0), fd_k=overrides.pop("fd_k", 3.0),
                       arena=sc.arena, flags={**flags, **overrides})
    roster = [s.node_id for s in world.node_specs]
    agents = {}
    brain = OracleBrain(world) if cls is OracleAgent else None
    for spec in world.node_specs:
        a = cls(world.bodies[spec.node_id], roster, acfg, world.rngs.get("agent:" + spec.node_id))
        if brain is not None:
            a.brain = brain
        agents[spec.node_id] = a
    world.attach(agents)
    out = world.run()
    if not keep_timeline:
        out.pop("timeline", None)
    extra = {}
    for a in agents.values():
        for k, v in getattr(a, "stats", {}).items():
            extra["hesk_" + k] = extra.get("hesk_" + k, 0) + v
    out.update(extra)
    out.update({"algo": algo, "seed": seed, "scenario_hash": config_hash(sc.to_dict()),
                "python": platform.python_version()})
    return out


def seed_for(suite: str, cell: str, rep: int) -> int:
    """Seed depends on the scenario cell and repetition, never on the algorithm,
    so every algorithm faces the exact same fleet, mission and fault draw."""
    return derive_seed(suite, cell, rep)
