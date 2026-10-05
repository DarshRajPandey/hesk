"""Centralized dispatch: elected leader + optimal assignment (Kuhn-Munkres).

This is the fleet-manager / ground-control-station architecture: one
coordinator holds the global picture and solves the assignment problem
optimally every REPLAN seconds. Leader = lowest id the node believes alive
(bully election over the shared failure detector).

quorum=True  (default) — Raft-style safety: a leader may only issue plans
              while it hears a strict majority of the original fleet; a
              minority partition keeps executing its last plan but cannot
              re-plan (CP in CAP terms).
quorum=False — every partition elects its own leader and re-plans (AP).

`OracleAgent` solves the same problem from ground truth with zero comms.
It is *not* an upper bound (no coalitions) but anchors what perfect
information buys a 1:1 optimal assigner.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import numpy as np
from scipy.optimize import linear_sum_assignment

from hesk_sim.agents.base import AgentBase, best_feasible_tier
from hesk_sim.network import Message
from hesk_sim.world import Intent

REPLAN = 2.0
W_TRAVEL = 0.1
HYSTERESIS = 0.05
NEG = -1e6


def solve(nodes: List[Tuple[str, dict, tuple]], tasks, now: float, arena: float,
          current: Dict[str, str]) -> Dict[str, Tuple[str, int]]:
    """Max-utility 1:1 assignment. nodes: (id, caps, pos). Returns task -> (node, tier)."""
    if not nodes or not tasks:
        return {}
    V = np.full((len(nodes), len(tasks)), NEG)
    T = np.zeros((len(nodes), len(tasks)), dtype=int)
    for a, (nid, caps, pos) in enumerate(nodes):
        for b, task in enumerate(tasks):
            tier, q = best_feasible_tier(caps, task, now)
            if tier is None:
                continue
            d = ((pos[0] - task.pos[0]) ** 2 + (pos[1] - task.pos[1]) ** 2) ** 0.5 / arena
            V[a, b] = task.defn.mission_priority * q - W_TRAVEL * d + (HYSTERESIS if current.get(task.id) == nid else 0.0)
            T[a, b] = tier
    r, c = linear_sum_assignment(V, maximize=True)
    return {tasks[b].id: (nodes[a][0], int(T[a, b])) for a, b in zip(r, c) if V[a, b] > NEG / 2}


class CentralAgent(AgentBase):
    def on_start(self) -> None:
        self.quorum = bool(self.cfg.flag("quorum", True))
        self.plan: Dict[str, Tuple[str, int]] = {}
        self.plan_term: Tuple[float, str] = (-1.0, "")
        self.next_plan = 0.0
        self.dynamic: Dict[str, object] = {}

    def heartbeat_payload(self) -> dict:
        return {"cat": list(self.dynamic.values())}

    def on_task_discovered(self, task, now: float) -> None:
        self.tasks[task.id] = task
        self.dynamic[task.id] = task

    def is_leader(self, now: float) -> bool:
        view = self.alive_view(now)
        if view[0] != self.id:
            return False
        return (not self.quorum) or len(view) * 2 > len(self.roster)

    def on_tick(self, now: float) -> None:
        if now < self.next_plan or not self.is_leader(now):
            return
        self.next_plan = now + REPLAN
        view = self.alive_view(now)
        nodes = [(self.id, self.body.caps, self.body.pos)]
        nodes += [(n, self.peers[n].caps, self.peers[n].pos) for n in view if n != self.id and self.peers[n].caps]
        tasks = [t for _, t in sorted(self.tasks.items()) if t.arrival <= now]
        current = {tid: nid for tid, (nid, _) in self.plan.items()}
        plan = solve(nodes, tasks, now, self.cfg.arena, current)
        self.plan, self.plan_term = plan, (now, self.id)
        defs = [self.dynamic[t] for t in plan if t in self.dynamic]  # plan carries specs of newly found tasks
        self.send("PLAN", {"plan": plan, "term": self.plan_term, "defs": defs}, size=48 + 16 * len(plan) + 64 * len(defs))

    def handle(self, msg: Message, now: float) -> None:
        p = msg.payload
        if msg.kind == "HB":
            for t in p.get("cat", ()):
                if t.id not in self.tasks:
                    self.tasks[t.id] = t
                    self.dynamic[t.id] = t
        elif msg.kind == "PLAN":
            for t in p.get("defs", ()):
                self.tasks.setdefault(t.id, t)
            # Follow the newest plan from whoever this node believes is (or was) the leader.
            if p["term"][0] >= self.plan_term[0] and msg.src == self.alive_view(now)[0]:
                self.plan, self.plan_term = p["plan"], p["term"]

    def intent(self) -> Optional[Intent]:
        for tid, (nid, tier) in self.plan.items():
            if nid == self.id:
                # A follower knows its own body: serve the best tier it can actually meet.
                own_tier = best_feasible_tier(self.body.caps, self.tasks[tid], 0.0)[0]
                return Intent(tid, own_tier, (self.id,)) if own_tier is not None else None
        return None


class OracleBrain:
    """Shared god's-eye planner (reads World directly — reference only)."""

    def __init__(self, world):
        self.world = world
        self.plan: Dict[str, Tuple[str, int]] = {}
        self.next_plan = 0.0

    def refresh(self, now: float) -> None:
        if now < self.next_plan:
            return
        self.next_plan = now + REPLAN
        w = self.world
        nodes = [(n, b.caps, b.pos) for n, b in sorted(w.bodies.items()) if b.alive]
        tasks = [t for t in w.tasks if t.arrival <= now]
        current = {tid: nid for tid, (nid, _) in self.plan.items()}
        self.plan = solve(nodes, tasks, now, w.cfg.arena, current)
        self.by_node = {nid: (tid, tier) for tid, (nid, tier) in self.plan.items()}


class OracleAgent(AgentBase):
    brain: OracleBrain = None  # type: ignore

    def send_heartbeat(self) -> None:  # oracle needs no communication
        pass

    def on_tick(self, now: float) -> None:
        self.brain.refresh(now)

    def intent(self) -> Optional[Intent]:
        x = getattr(self.brain, "by_node", {}).get(self.id)
        return Intent(x[0], x[1], (self.id,)) if x else None
