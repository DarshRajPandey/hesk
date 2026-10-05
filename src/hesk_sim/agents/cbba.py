"""Consensus-Based Bundle Algorithm (Choi, Brunet & How, IEEE T-RO 2009).

Bundle length L=1 (each drone serves one persistent task at a time), which
is the CBAA special case, run asynchronously over heartbeats. Consensus
uses the full receiver-side decision table (Table 1 of the paper) over
winning bids y, winners z and information timestamps s.

Made dynamic-environment fair: winners that the shared failure detector
suspects are reset, and bids are tier-aware (score = priority x quality of
the best tier the drone can serve alone - travel). CBBA does not form
coalitions and has no notion of scarcity: those are HESK's claims.
"""
from __future__ import annotations

from typing import Dict, Optional

from hesk_sim.agents.base import AgentBase, best_feasible_tier
from hesk_sim.network import Message
from hesk_sim.world import Intent

W_TRAVEL = 0.1


class CBBAAgent(AgentBase):
    def on_start(self) -> None:
        self.y: Dict[str, float] = {}
        self.z: Dict[str, Optional[str]] = {}
        self.s: Dict[str, float] = {self.id: 0.0}
        self.dynamic: Dict[str, object] = {}
        self.my_tier: Optional[int] = None

    def heartbeat_payload(self) -> dict:
        return {"y": dict(self.y), "z": dict(self.z), "s": dict(self.s), "cat": list(self.dynamic.values())}

    def on_task_discovered(self, task, now: float) -> None:
        self.tasks[task.id] = task
        self.dynamic[task.id] = task

    def score(self, tid: str, now: float):
        task = self.tasks[tid]
        tier, q = best_feasible_tier(self.body.caps, task, now)
        if tier is None:
            return None, 0.0
        return tier, task.defn.mission_priority * q - W_TRAVEL * self.travel_cost(task) + 1.0

    def _mine(self) -> Optional[str]:
        for tid, w in self.z.items():
            if w == self.id:
                return tid
        return None

    def on_tick(self, now: float) -> None:
        self.s[self.id] = now
        for tid, w in list(self.z.items()):
            if w is not None and w != self.id and self.suspected(w, now):
                self.y[tid], self.z[tid] = 0.0, None
        mine = self._mine()
        if mine is not None:
            tier, _ = self.score(mine, now)
            if tier is None:                       # lost the capability: drop the task
                self.y[mine], self.z[mine] = 0.0, None
            else:
                self.my_tier = tier
                return
        best, best_c, best_t = None, 0.0, None
        for tid, task in sorted(self.tasks.items()):
            if task.arrival > now:
                continue
            tier, c = self.score(tid, now)
            if tier is None:
                continue
            yj, zj = self.y.get(tid, 0.0), self.z.get(tid)
            if c > yj + 1e-12 or (abs(c - yj) <= 1e-12 and zj is not None and self.id < zj):
                if c > best_c:
                    best, best_c, best_t = tid, c, tier
        if best is not None:
            self.y[best], self.z[best], self.my_tier = best_c, self.id, best_t

    def _beats(self, yk: float, zk: str, yi: float, zi: Optional[str]) -> bool:
        if yk > yi + 1e-12:
            return True
        return abs(yk - yi) <= 1e-12 and zi is not None and zk is not None and zk < zi

    def handle(self, msg: Message, now: float) -> None:
        if msg.kind != "HB":
            return
        p, k, i = msg.payload, msg.src, self.id
        for t in p.get("cat", ()):
            if t.id not in self.tasks:
                self.tasks[t.id] = t
                self.dynamic[t.id] = t
        sk = p["s"]
        si = self.s
        sk = dict(sk)
        sk[k] = now
        for j in set(p["z"]) | set(self.z):
            zk, yk = p["z"].get(j), p["y"].get(j, 0.0)
            zi, yi = self.z.get(j), self.y.get(j, 0.0)
            act = "leave"

            def newer(m):
                return sk.get(m, -1.0) > si.get(m, -1.0)

            if zk == k:
                if zi == i:
                    act = "update" if self._beats(yk, zk, yi, zi) else "leave"
                elif zi == k or zi is None:
                    act = "update"
                else:
                    act = "update" if (newer(zi) or self._beats(yk, zk, yi, zi)) else "leave"
            elif zk == i:
                if zi == k:
                    act = "reset"
                elif zi not in (i, None) and newer(zi):
                    act = "reset"
            elif zk is not None:  # zk = m ∉ {i, k}
                m = zk
                if zi == i:
                    act = "update" if (newer(m) and self._beats(yk, zk, yi, zi)) else "leave"
                elif zi == k:
                    act = "update" if newer(m) else "reset"
                elif zi == m:
                    act = "update" if newer(m) else "leave"
                elif zi is None:
                    act = "update" if newer(m) else "leave"
                else:  # zi = n ∉ {i, k, m}
                    n = zi
                    if newer(m) and newer(n):
                        act = "update"
                    elif newer(m) and self._beats(yk, zk, yi, zi):
                        act = "update"
                    elif newer(n) and si.get(m, -1.0) > sk.get(m, -1.0):
                        act = "reset"
            else:  # zk is None
                if zi == k:
                    act = "update"
                elif zi not in (i, None) and newer(zi):
                    act = "update"
            if act == "update":
                self.y[j], self.z[j] = yk, zk
            elif act == "reset":
                self.y[j], self.z[j] = 0.0, None
        for m, t in sk.items():
            if m != i and t > si.get(m, -1.0):
                si[m] = t

    def intent(self) -> Optional[Intent]:
        mine = self._mine()
        if mine is None or self.my_tier is None:
            return None
        return Intent(mine, self.my_tier, (self.id,))
