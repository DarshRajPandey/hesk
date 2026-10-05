"""E11: does scarcity-aware allocation (Algorithm 004) preserve mission utility?

Tasks arrive online and each consumes the node it is assigned to. Policies use HESK's real
eligibility / match-quality / scarcity / cost functions; the oracle is the offline
max-weight bipartite matching (Hungarian). The score is the share of oracle utility achieved
(priority-weighted tasks served), so 1.0 is unbeatable and values are comparable across loads.

The simulator knows the whole fleet and task list only to compute the oracle.
"""
from __future__ import annotations

import itertools
import random
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

from hesk.capabilities.matching import check_eligibility, compute_match_quality
from hesk.capabilities.model import CapabilityState
from hesk.core.types import DimType
from hesk.tasks.allocation import compute_scarcity_penalty, compute_system_cost, evaluate_bids
from hesk.tasks.model import Bid, TaskRequirement

DIMS = ("rgb", "compute", "thermal", "lidar")
RARE = ("thermal", "lidar")
BASE_CONSUMPTION = 0.1  # as in the algorithm's worked example (docs/algorithms/004)

POLICIES = (
    "random", "best-quality", "tightest-fit",
    "hesk(w=0)", "hesk(w=0.5)", "hesk(w=1)", "hesk(w=2)", "hesk(w=4)", "hesk(w=8)", "hesk(w=16)",
    "hesk(w=2,available)", "hesk(w=2,known=0.5)",
)


def make_fleet(rng: random.Random, n: int, p_thermal: float, p_lidar: float) -> List[CapabilityState]:
    fleet = []
    for i in range(n):
        d = {"rgb": rng.uniform(0.5, 1.0) if rng.random() < 0.95 else 0.0, "compute": rng.uniform(0.2, 1.0),
             "thermal": rng.uniform(0.5, 1.0) if rng.random() < p_thermal else 0.0,
             "lidar": rng.uniform(0.5, 1.0) if rng.random() < p_lidar else 0.0}
        fleet.append(CapabilityState(f"n{i:02d}", 0.0, d))
    return fleet


def make_tasks(rng: random.Random, m: int, rare_share: float) -> List[Dict[str, Any]]:
    tasks = []
    for j in range(m):
        if rng.random() < rare_share:
            dim = rng.choice(RARE)
            req = {dim: TaskRequirement(DimType.CONTINUOUS, threshold=rng.uniform(0.4, 0.8))}
            tasks.append({"id": j, "rare": True, "pi": rng.uniform(0.7, 1.0), "req": req,
                          "pref": {"rgb": TaskRequirement(DimType.CONTINUOUS, threshold=0.8)}})
        else:
            req = {"rgb": TaskRequirement(DimType.CONTINUOUS, threshold=rng.uniform(0.4, 0.7)),
                   "compute": TaskRequirement(DimType.CONTINUOUS, threshold=rng.uniform(0.2, 0.6))}
            tasks.append({"id": j, "rare": False, "pi": rng.uniform(0.2, 0.7), "req": req,
                          "pref": {"compute": TaskRequirement(DimType.CONTINUOUS, threshold=0.8)}})
    return tasks


def _eligible(task, nodes):
    return [n for n in nodes if check_eligibility(n, task["req"])]


def choose(policy: str, task, free: List[CapabilityState], fleet: List[CapabilityState], energy: Dict[str, float],
           rng: random.Random) -> Optional[str]:
    el = _eligible(task, free)
    if not el:
        return None
    if policy == "random":
        return rng.choice(el).node_id
    if policy == "best-quality":
        return max(el, key=lambda n: (compute_match_quality(n, task["pref"]), n.node_id)).node_id
    if policy == "tightest-fit":  # least total capability among the sufficient nodes
        return min(el, key=lambda n: (sum(v for v in n.dimensions.values()), n.node_id)).node_id
    assert policy.startswith("hesk(")
    w = float(policy[5:].split(",")[0].split("=")[1].rstrip(")"))
    swarm = free if "available" in policy else fleet
    if "known=" in policy:  # each bidder only knows a random subset of the swarm (plus itself)
        frac = float(policy.split("known=")[1].rstrip(")"))
        k = max(1, int(round(frac * len(swarm))))
        subset_seed = rng.random()
        sub_rng = random.Random(subset_seed)
    bids = []
    req_dims = set(task["req"])
    for n in el:
        sw = swarm
        if "known=" in policy:
            others = [m for m in swarm if m.node_id != n.node_id]
            sw = [n] + sub_rng.sample(others, min(len(others), k - 1))
        mq = compute_match_quality(n, task["pref"])
        pen = compute_scarcity_penalty(n, req_dims, sw)
        cost = compute_system_cost(mq, energy[n.node_id], BASE_CONSUMPTION, pen, w_scarcity=w)
        bids.append(Bid(task["id"], n.node_id, cost, mq, energy[n.node_id], n))
    return evaluate_bids(bids, str(task["id"])).assigned_node


def oracle_utility(tasks, fleet) -> float:
    import numpy as np
    from scipy.optimize import linear_sum_assignment
    u = np.array([[t["pi"] if check_eligibility(n, t["req"]) else 0.0 for n in fleet] for t in tasks])
    r, c = linear_sum_assignment(u, maximize=True)
    return float(u[r, c].sum())


def order_tasks(tasks, order: str, rng: random.Random):
    ts = tasks[:]
    if order == "random":
        rng.shuffle(ts)
    elif order == "common-first":  # adversarial for greedy: abundant demand consumes scarce nodes first
        ts.sort(key=lambda t: t["rare"])
    elif order == "rare-first":
        ts.sort(key=lambda t: not t["rare"])
    return ts


def trial(labels: Dict[str, Any], policy: str, seed: int) -> Dict[str, Any]:
    rng = random.Random(f"alloc:{seed}:fleet")
    n = int(labels.get("nodes", 20))
    fleet = make_fleet(rng, n, labels.get("p_thermal", 0.15), labels.get("p_lidar", 0.25))
    energy = {f.node_id: rng.uniform(0.3, 1.0) for f in fleet}
    tasks = make_tasks(random.Random(f"alloc:{seed}:tasks"), int(round(labels.get("load", 0.8) * n)), labels.get("rare_share", 0.3))
    arrivals = order_tasks(tasks, labels.get("order", "random"), random.Random(f"alloc:{seed}:order"))
    prng = random.Random(f"alloc:{seed}:policy")
    free = list(fleet)
    util = served = rare_served = 0.0
    for t in arrivals:
        pick = choose(policy, t, free, fleet, energy, prng)
        if pick is None:
            continue
        free = [f for f in free if f.node_id != pick]
        util += t["pi"]; served += 1; rare_served += int(t["rare"])
    opt = oracle_utility(tasks, fleet)
    n_rare = sum(t["rare"] for t in tasks)
    return {"utility_ratio": util / opt if opt else 1.0, "served_frac": served / len(tasks) if tasks else 1.0,
            "rare_served_frac": rare_served / n_rare if n_rare else None, "oracle_utility": opt}


def grid() -> Iterator[Tuple[Dict[str, Any], str]]:
    base = {"nodes": 20, "load": 0.8, "rare_share": 0.3, "order": "random"}
    for load in (0.4, 0.6, 0.8, 1.0, 1.2):
        for order in ("random", "common-first", "rare-first"):
            for pol in POLICIES:
                yield {**base, "load": load, "order": order, "sweep": "load"}, pol
    for share in (0.1, 0.2, 0.4, 0.6):
        for pol in POLICIES:
            yield {**base, "rare_share": share, "order": "common-first", "sweep": "rare_share"}, pol
