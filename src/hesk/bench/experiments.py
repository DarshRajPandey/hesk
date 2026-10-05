"""Experiment definitions. Every experiment is a list of cells; a cell is (labels, Params, impls)."""
from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from typing import Dict, List, Sequence, Tuple

from hesk.bench.impls import BASELINES, BEST_LEGACY, LATTICE, LEGACY
from hesk.sim.scenario import Params

BASE = Params(claimants=3)  # 12 nodes, 3 partition groups, one claimant per group
MAIN = replace(BASE, n_obs=0)  # ownership + counters + resources
OBS = replace(BASE, n_chain=0, n_contest=0, n_counter=0, n_res=0, n_obs=3)
OWN_ONLY = replace(BASE, n_chain=0, n_counter=0, n_obs=0, n_res=0, n_contest=8)

OWN_IMPLS = ("legacy/reconcile/relay", BEST_LEGACY, "hesk-l", "hesk-l/exact", "hesk-l/eps-resolver")
ALL_IMPLS = LEGACY + LATTICE


@dataclass(frozen=True)
class Cell:
    exp: str
    labels: Tuple[Tuple[str, object], ...]
    params: Params
    impls: Tuple[str, ...]

    def label_dict(self) -> Dict[str, object]:
        return dict(self.labels)


def _cell(exp: str, labels: Dict[str, object], params: Params, impls: Sequence[str]) -> Cell:
    return Cell(exp, tuple(sorted(labels.items())), params, tuple(impls))


def build(exp: str) -> List[Cell]:
    out: List[Cell] = []
    if exp == "E1_audit":  # headline: every implementation, both workloads, default parameters
        out.append(_cell(exp, {"workload": "main"}, MAIN, ALL_IMPLS))
        out.append(_cell(exp, {"workload": "obs"}, OBS, ALL_IMPLS))
    elif exp == "E2_groups":  # number of partition groups == number of concurrent claimants
        for g in (1, 2, 3, 4, 6):
            out.append(_cell(exp, {"groups": g}, replace(OWN_ONLY, n_groups=g, claimants=g), OWN_IMPLS))
    elif exp == "E3_spread":  # how close the claimants' progress values are
        for s in (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4):
            out.append(_cell(exp, {"spread": s}, replace(OWN_ONLY, n_groups=4, claimants=4, claim_spread=s), OWN_IMPLS))
    elif exp == "E4_handoff_gap":  # causal handoffs: how long after seeing a claim a node takes over
        for gap in (0.5, 1.0, 2.0, 3.0, 4.0, 5.5, 8.0, 12.0, 20.0):
            p = replace(MAIN, handoff_gap=gap, n_contest=0, n_counter=0, n_res=0, t_connected=max(20.0, 6 + 3 * gap + 6))
            out.append(_cell(exp, {"gap": gap}, p, ("legacy/gossip/relay", "legacy/reconcile/relay", "legacy/gossip/direct", "hesk-l")))
    elif exp == "E5_skew":  # wall-clock skew between nodes
        for sk in (0.0, 0.1, 0.5, 1.0, 2.0, 5.0):
            out.append(_cell(exp, {"skew": sk}, replace(MAIN, clock_skew=sk, n_chain=0, n_contest=0, n_counter=0),
                             ("legacy/reconcile/relay", BEST_LEGACY, "hesk-l", "hesk-l/-lww")))
    elif exp == "E6_scale":  # swarm size: cost of the fix
        for n in (6, 12, 24, 48):
            out.append(_cell(exp, {"nodes": n}, replace(MAIN, n_nodes=n), (BEST_LEGACY, "hesk-l")))
    elif exp == "E7_ablation":  # one design choice at a time, default and harsh network
        harsh = replace(BASE, n_groups=4, claimants=4, loss=0.2, clock_skew=1.0)
        for name, p in (("default", BASE), ("harsh", harsh)):
            out.append(_cell(exp, {"network": name, "workload": "main"}, replace(p, n_obs=0), LATTICE))
            out.append(_cell(exp, {"network": name, "workload": "obs"},
                             replace(p, n_chain=0, n_contest=0, n_counter=0, n_res=0, n_obs=3), LATTICE))
    elif exp == "E8_intra_group":  # stress: several concurrent claimants inside ONE connected component
        for c in (2, 4, 8):
            out.append(_cell(exp, {"claimants": c}, replace(OWN_ONLY, n_groups=2, claimants=c, one_per_group=False), OWN_IMPLS))
    elif exp == "E10_root_cause":  # factorial attribution on the LEGACY code: which defects matter?
        import itertools
        impls = []
        for mode, relay in itertools.product(("reconcile", "always"), ("relay", "direct")):
            for mask in itertools.product((0, 1), repeat=3):
                patches = [n for n, m in zip(("resolver", "window", "clock"), mask) if m]
                impls.append(f"legacy/{mode}/{relay}" + "".join("+" + n for n in patches))
        for gap, restart in itertools.product((2.0, 8.0), (False, True)):
            p = replace(MAIN, n_counter=0, n_res=0, n_contest=6, handoff_gap=gap, chain_restart=restart,
                        t_connected=max(20.0, 6 + 3 * gap + 6))
            out.append(_cell(exp, {"gap": gap, "restart": restart}, p, impls))
    elif exp == "E12_baselines":  # head-to-head against two conventional designs
        impls = ("hesk-l",) + BASELINES + ("legacy/reconcile/direct", "legacy/always/relay")
        for split, skew, gap in (("even", 0.1, 2.0), ("majority", 0.1, 2.0), ("even", 1.0, 1.0), ("majority", 1.0, 1.0)):
            out.append(_cell(exp, {"split": split, "skew": skew, "gap": gap},
                             replace(MAIN, split=split, clock_skew=skew, handoff_gap=gap), impls))
    elif exp == "E13_failure":  # adversarial sweeps: packet loss, crashes, latency, partition length
        impls = ("hesk-l",) + BASELINES + ("legacy/reconcile/direct",)
        two = replace(MAIN, n_groups=2, split="majority")
        for loss in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            out.append(_cell(exp, {"sweep": "loss", "x": loss}, replace(two, loss=loss), impls))
        for loss in (0.0, 0.1, 0.2, 0.3, 0.4, 0.5):  # control: same loss, no partition (quorum has 5 spare acks)
            out.append(_cell(exp, {"sweep": "loss_connected", "x": loss}, replace(MAIN, n_groups=1, claimants=1, loss=loss), impls))
        for c in (0.0, 0.1, 0.25, 0.4, 0.5, 0.6, 0.75):
            out.append(_cell(exp, {"sweep": "crash", "x": c}, replace(MAIN, n_groups=1, crash_frac=c), impls))
        for lat in (0.05, 0.15, 0.5, 1.0, 2.0):
            out.append(_cell(exp, {"sweep": "latency", "x": lat}, replace(two, latency=lat, jitter=0.66 * lat), impls))
        for tp in (5.0, 15.0, 45.0, 90.0):
            out.append(_cell(exp, {"sweep": "partition_s", "x": tp}, replace(MAIN, t_part=tp), impls))
    else:
        raise KeyError(exp)
    return out


EXPERIMENTS = ("E1_audit", "E2_groups", "E3_spread", "E4_handoff_gap", "E5_skew", "E6_scale", "E7_ablation", "E8_intra_group", "E10_root_cause", "E12_baselines", "E13_failure")
SEEDS = {"E1_audit": 100, "E7_ablation": 100, "E11_alloc": 200, "E12_baselines": 100}  # default elsewhere: 60
DEFAULT_SEEDS = 60
