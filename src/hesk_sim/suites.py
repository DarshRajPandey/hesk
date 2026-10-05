"""Declarative experiment grids. Each suite yields jobs:
(suite, cell, scenario overrides, algo, agent overrides, rep).

Within a cell every algorithm sees the same seed, hence the same fleet,
mission, task arrival times and fault schedule (common random numbers).
Per-packet loss draws differ, because they depend on each algorithm's
traffic. Pairing by seed is what makes the paired statistics valid.
"""
from __future__ import annotations

from typing import Dict, Iterator, List, Tuple

MAIN = ["oracle", "hesk", "hesk2", "hesk3", "cbba", "central", "central_noquorum", "cnp"]
CORE = ["hesk3", "cbba", "central", "cnp"]
ABLATIONS = ["hesk3", "abl-lease", "abl-coalscarcity", "abl-scarcity", "abl-tiers", "abl-coalitions",
             "abl-upgrade", "abl-gossip", "abl-reconcile", "abl-lww", "abl-raw008"]

ADVERSARIAL = dict(loss=0.2, burst_len=6.0, partitions=[(150.0, 300.0, 2)], kill_frac=0.25,
                   kill_mode="scarce", n_degrade=3)

CONDITIONS: Dict[str, dict] = {
    "nominal": {},
    "loss30": dict(loss=0.3),
    "partition2": dict(partitions=[(150.0, 300.0, 2)]),
    "attrition30": dict(kill_frac=0.3),
    "adversarial": ADVERSARIAL,
}

Job = Tuple[str, str, dict, str, dict, int]


def _grid(suite: str, cells: Dict[str, Tuple[dict, dict]], algos: List[str], reps: int) -> Iterator[Job]:
    for cell, (scen, agent) in cells.items():
        for rep in range(reps):
            for algo in algos:
                yield (suite, cell, scen, algo, agent, rep)


def suite_jobs(name: str, reps: int | None = None) -> List[Job]:
    if name == "baseline":
        r = reps or 30
        cells = {c: (s, {}) for c, s in CONDITIONS.items()}
        return list(_grid(name, cells, MAIN, r))
    if name == "loss":
        r = reps or 20
        cells = {f"loss={p:.1f}": (dict(loss=p), {}) for p in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9]}
        return list(_grid(name, cells, ["hesk", "hesk2", "hesk3", "cbba", "central", "cnp"], r))
    if name == "burst":
        r = reps or 15
        cells = {f"loss={p:.1f},burst={b:g}": (dict(loss=p, burst_len=b), {})
                 for p in [0.2, 0.4, 0.6] for b in [1, 4, 16, 64]}
        return list(_grid(name, cells, CORE, r))
    if name == "partition":
        r = reps or 15
        cells = {f"k={k},dur={d}": (dict(partitions=[(150.0, 150.0 + d, k)]), {})
                 for k in [2, 3, 4] for d in [60, 150, 300]}
        return list(_grid(name, cells, ["hesk3", "cbba", "central", "central_noquorum"], r))
    if name == "attrition":
        r = reps or 10
        cells = {f"kill={f:.1f},mode={m}": (dict(kill_frac=f, kill_mode=m), {})
                 for m in ["random", "scarce", "leader"] for f in [0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6]}
        return list(_grid(name, cells, CORE, r))
    if name == "latency":
        r = reps or 15
        cells = {f"lat={l:g}": (dict(latency=l, jitter=l / 2), {}) for l in [0.02, 0.1, 0.25, 0.5, 1.0, 2.0]}
        return list(_grid(name, cells, CORE, r))
    if name == "ablation":
        r = reps or 30
        cells = {c: (CONDITIONS[c], {}) for c in ["nominal", "loss30", "adversarial"]}
        return list(_grid(name, cells, ABLATIONS, r))
    if name == "fd":
        r = reps or 10
        cells = {f"fd_k={k:g},loss={p:.1f}": (dict(loss=p), {"fd_k": k})
                 for k in [1.5, 3, 6, 12] for p in [0.0, 0.3, 0.5, 0.7]}
        return list(_grid(name, cells, ["hesk2", "hesk3", "cbba", "central"], r))
    if name == "scale":
        r = reps or 5
        cells = {f"n={n}": (dict(n_nodes=n), {}) for n in [12, 24, 48, 96]}
        return list(_grid(name, cells, ["hesk3", "cbba", "central", "oracle"], r))
    raise KeyError(name)


SUITES = ["baseline", "loss", "burst", "partition", "attrition", "latency", "ablation", "fd", "scale"]
