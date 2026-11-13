"""Generate parity fixtures from the reference Python kernel.

Runs the real `hesk` package over the laboratory's scenario catalog and records
the results. `tests/parity.test.ts` replays the same inputs through the
TypeScript port and requires identical output.

    pip install -e .            # from the repository root
    python3 frontend/scripts/gen_parity_fixtures.py
"""
import json
import math
from pathlib import Path

import hesk.ledger.ledger as ledger_mod
from hesk.capabilities.matching import compute_full_match
from hesk.capabilities.model import CapabilityState
from hesk.coalitions.formation import LinkMetrics, form_coalition
from hesk.core.types import DimType, PriorityClass
from hesk.degradation.logic import LocalLedger, handle_degradation_trigger
from hesk.degradation.model import DegradationTrigger, DegradationTriggerType
from hesk.ledger.ledger import LocalStateLedger
from hesk.ledger.model import StateSemanticType
from hesk.ledger.reconciliation import get_unseen_events, handle_reconnection
from hesk.tasks.allocation import compute_scarcity_penalty, compute_system_cost, evaluate_bids
from hesk.tasks.model import (ActiveTask, Bid, DataFlowRequirement, DegradationTier,
                              TaskDefinition, TaskRequirement, TaskStatus)

ROOT = Path(__file__).resolve().parent.parent
CATALOG = json.loads((ROOT / "src/sim/catalog.json").read_text())
PRESET = "baseline"
BASE_CONSUMPTION = 0.1


def req(r):
    return TaskRequirement(dim_type=DimType[r["dimType"]], value=r.get("value"), threshold=r.get("threshold"),
                           required_set=set(r["requiredSet"]) if "requiredSet" in r else None)


def tier(t):
    return DegradationTier(
        tier_level=t["tierLevel"], quality_estimate=t["qualityEstimate"],
        required={k: req(v) for k, v in t["required"].items()},
        preferred={k: req(v) for k, v in t["preferred"].items()},
        data_flow=[DataFlowRequirement(f["sourceCapability"], f["sinkCapability"], f["bandwidthKbps"], f.get("maxLatencyMs"))
                   for f in t["dataFlow"]])


TASKS = [TaskDefinition(t["taskId"], PriorityClass[t["priorityClass"]], t["missionPriority"], t["qMin"], [tier(x) for x in t["tiers"]])
         for t in CATALOG["tasks"]]

NODES, POS, ENERGY = [], {}, {}
counts = {}
for i, n in enumerate(CATALOG["presets"][PRESET]["nodes"]):
    a = CATALOG["archetypes"][n["archetype"]]
    counts[n["archetype"]] = counts.get(n["archetype"], 0) + 1
    nid = f'{a["prefix"]}-{counts[n["archetype"]]}'
    NODES.append(CapabilityState(nid, 0.0, dict(a["dims"])))
    POS[nid] = (n["x"], n["y"])
    ENERGY[nid] = round(1.0 - 0.03 * i, 4)


class Links(LinkMetrics):
    def _d(self, a, b):
        return math.dist(POS[a], POS[b])

    def get_bandwidth(self, a, b):
        return CATALOG["maxBandwidthKbps"] * max(0.0, 1.0 - self._d(a, b) / CATALOG["commRange"])

    def get_latency(self, a, b):
        return CATALOG["baseLatencyMs"] + CATALOG["latencyPerUnitMs"] * self._d(a, b)


def assignee_out(a):
    if a is None:
        return None
    return a if isinstance(a, str) else {"members": a.members, "roles": a.role_assignment, "cost": a.estimated_cost}


out = {"preset": PRESET, "match": [], "allocation": [], "coalition": [], "degradation": [], "reconciliation": None}

for t in TASKS:
    for tr in t.tiers:
        for n in NODES:
            m = compute_full_match(n, tr.required, tr.preferred)
            out["match"].append({"task": t.task_id, "tier": tr.tier_level, "node": n.node_id, "eligible": m.eligible,
                                 "quality": m.quality, "unmet": sorted(m.unmet_required)})
        bids = []
        for n in NODES:
            m = compute_full_match(n, tr.required, tr.preferred)
            if not m.eligible:
                continue
            pen = compute_scarcity_penalty(n, set(tr.required), NODES)
            cost = compute_system_cost(m.weighted_quality, ENERGY[n.node_id], BASE_CONSUMPTION, pen)
            bids.append(Bid(t.task_id, n.node_id, cost, m.weighted_quality, ENERGY[n.node_id], n))
        r = evaluate_bids(bids, t.task_id)
        out["allocation"].append({"task": t.task_id, "tier": tr.tier_level, "bids": {b.node_id: b.system_cost for b in bids},
                                  "winner": r.assigned_node, "runnerUp": r.runner_up_node})
        for label, cands in (("all", NODES), ("no_isr", [n for n in NODES if not n.node_id.startswith("ISR")])):
            c = form_coalition(t.task_id, tr.required, tr.data_flow, cands, Links(), "init")
            out["coalition"].append({"task": t.task_id, "tier": tr.tier_level, "candidates": label, "success": c.success,
                                     "result": assignee_out(c.coalition) if c.success else None})

# Degradation: fixed initial assignment, then lose each assigned node in turn.
initial, taken = {}, set()
for t in TASKS:
    bids = []
    for n in NODES:
        if n.node_id in taken:
            continue
        m = compute_full_match(n, t.tiers[0].required, t.tiers[0].preferred)
        if m.eligible:
            bids.append(Bid(t.task_id, n.node_id, 1.0 - m.quality, m.quality, 1.0, n))
    w = evaluate_bids(bids, t.task_id).assigned_node
    if w:
        initial[t.task_id] = w
        taken.add(w)
out["initial"] = initial


class Ledger(LocalLedger):
    def __init__(self, tasks):
        self.tasks = tasks

    def get_affected_tasks(self, trigger):
        return [t for t in self.tasks if t.assignee == trigger.source_node]

    def get_all_active_tasks(self):
        return self.tasks

    def release_task_resources(self, task):
        return [task.assignee] if isinstance(task.assignee, str) else []


for lost in sorted(taken):
    tasks = [ActiveTask(t, 0, TaskStatus.EXECUTING, initial[t.task_id]) if t.task_id in initial
             else ActiveTask(t, 0, TaskStatus.ABANDONED, None) for t in TASKS]
    busy = {t.assignee for t in tasks if t.assignee and t.assignee != lost}
    known = [n for n in NODES if n.node_id not in busy]
    plan = handle_degradation_trigger(DegradationTrigger(DegradationTriggerType.NODE_LOSS, lost), Ledger(tasks), known, Links())
    out["degradation"].append({
        "lost": lost, "known": [n.node_id for n in known],
        "tierChanges": {k: list(v) for k, v in plan.tier_changes.items()},
        "assignments": {k: assignee_out(v) for k, v in plan.new_assignments.items()},
        "abandoned": plan.abandoned_tasks, "utilityBefore": plan.utility_before, "utilityAfter": plan.utility_after,
        "trace": [[e.task_id, e.action.value] for e in plan.decision_trace]})

# Reconciliation: scripted writes on two replicas with a controlled clock.
clock = {"t": 0.0}
ledger_mod.local_wall_time = lambda: clock["t"]
SEM = {"SET_LIKE": StateSemanticType.SET_LIKE, "COUNTER": StateSemanticType.COUNTER,
       "EXCLUSIVE_OWNERSHIP": StateSemanticType.EXCLUSIVE_OWNERSHIP, "RESOURCE": StateSemanticType.RESOURCE}
own = lambda a, p, q: {"assignee": a, "progress": p, "match_quality": q}
ops = [
    ["a", 0, "zones", ["A1"], "SET_LIKE"], ["a", 0, "beacons", 3, "COUNTER"],
    ["a", 5, "zones", ["A1", "B2"], "SET_LIKE"], ["b", 5, "zones", ["C3", "D4"], "SET_LIKE"],
    ["a", 10, "task_owner.map", own("ISR-1", 0.60, 0.75), "EXCLUSIVE_OWNERSHIP"],
    ["b", 12, "task_owner.map", own("SCT-3", 0.30, 0.82), "EXCLUSIVE_OWNERSHIP"],
    ["a", 14, "task_owner.trk", own("ISR-2", 0.20, 0.50), "EXCLUSIVE_OWNERSHIP"],
    ["b", 15, "task_owner.trk", own("SCT-1", 0.22, 0.90), "EXCLUSIVE_OWNERSHIP"],
    ["a", 16, "task_owner.rly", own("RLY-2", 0.10, 1.0), "EXCLUSIVE_OWNERSHIP"],
    ["b", 16, "task_owner.rly", own("RLY-1", 0.10, 1.0), "EXCLUSIVE_OWNERSHIP"],
    ["a", 20, "node.X.status", "UNREACHABLE", "RESOURCE"], ["b", 40, "node.X.status", "ACTIVE", "RESOURCE"],
    ["a", 41, "node.Y.status", "ACTIVE", "RESOURCE"], ["b", 42, "node.Y.status", "UNREACHABLE", "RESOURCE"],
    ["b", 45, "task_owner.remote_only", own("THM-2", 0.4, 1.0), "EXCLUSIVE_OWNERSHIP"],
    ["a", 50, "beacons", 9, "COUNTER"], ["b", 50, "beacons", 7, "COUNTER"],
]
led = {"a": LocalStateLedger("a"), "b": LocalStateLedger("b")}
for who, t, key, value, sem in ops:
    clock["t"] = float(t)
    led[who].write_local(key, set(value) if sem == "SET_LIKE" else value, SEM[sem])
clock["t"] = 60.0
effects = []
trace = handle_reconnection(led["a"], "b", led["b"].lamport_clock, led["b"].version_vector,
                            get_unseen_events(led["b"].event_log, led["a"].version_vector), effects.append)
norm = lambda v: sorted(v) if isinstance(v, set) else v
out["reconciliation"] = {
    "ops": ops, "at": 60,
    "conflictsFound": trace.conflicts_found, "entriesMerged": trace.entries_merged,
    "resolutions": {c.key: {"strategy": c.resolution.strategy, "winner": c.resolution.winning_source, "reason": c.resolution.reason}
                    for c in trace.resolution_details},
    "sideEffects": sorted([e.type.value, e.target, e.task] for e in effects),
    "entries": {k: norm(e.value) for k, e in sorted(led["a"].entries.items())},
    "lamport": led["a"].lamport_clock,
}

dest = ROOT / "tests/fixtures/parity.json"
dest.write_text(json.dumps(out, indent=1, sort_keys=True) + "\n")
print(f"wrote {dest.relative_to(ROOT)}: {len(out['match'])} match, {len(out['allocation'])} allocation, "
      f"{len(out['coalition'])} coalition, {len(out['degradation'])} degradation cases")
