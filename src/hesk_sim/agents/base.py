"""Shared agent scaffolding: heartbeat, failure detector, peer view.

Every algorithm (HESK and all baselines) gets the *same* failure detector
and heartbeat cadence, so differences in outcome come from the
coordination logic, not from one side having a better radio stack.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from hesk.capabilities.model import CapabilityState

from hesk_sim.network import Message, Network
from hesk_sim.engine import EventLoop
from hesk_sim.world import Body, Intent
from hesk_sim.scenario import SimTask

TICK = 0.5


@dataclass
class PeerInfo:
    last_heard: float
    caps: dict
    pos: tuple
    energy: float
    busy: Optional[str]
    report_time: float


@dataclass
class AgentConfig:
    name: str = "hesk"
    hb: float = 1.0          # heartbeat period (s)
    fd_k: float = 3.0        # suspect a peer after fd_k * hb of silence
    arena: float = 1000.0
    flags: Dict[str, object] = field(default_factory=dict)

    def flag(self, key: str, default=None):
        return self.flags.get(key, default)


class AgentBase:
    def __init__(self, body: Body, roster: List[str], cfg: AgentConfig, rng: random.Random):
        self.body = body
        self.id = body.node_id
        self.roster = sorted(roster)
        self.cfg = cfg
        self.rng = rng
        self.peers: Dict[str, PeerInfo] = {}
        self.tasks: Dict[str, SimTask] = {}
        self.loop: EventLoop = None  # type: ignore
        self.net: Network = None     # type: ignore
        self._next_hb = 0.0

    # ── lifecycle ────────────────────────────────────────────────────
    def start(self, loop: EventLoop, net: Network, initial_tasks: List[SimTask]) -> None:
        self.loop, self.net = loop, net
        for t in initial_tasks:
            self.tasks[t.id] = t
        # Mission plan includes the roster: everyone starts believing everyone is alive.
        for n in self.roster:
            if n != self.id:
                self.peers[n] = PeerInfo(0.0, {}, (0.0, 0.0), 1.0, None, -1e9)
        self._next_hb = self.rng.uniform(0, self.cfg.hb)
        self.loop.at(self.rng.uniform(0, TICK), self._tick)
        self.on_start()

    def _tick(self) -> None:
        if not self.body.alive:
            return
        now = self.loop.now
        if now >= self._next_hb:
            self._next_hb = now + self.cfg.hb
            self.send_heartbeat()
        self.on_tick(now)
        self.loop.after(TICK, self._tick)

    # ── messaging ────────────────────────────────────────────────────
    def send(self, kind: str, payload: dict, size: int = 64, dst: Optional[str] = None) -> None:
        self.net.send(Message(kind, self.id, payload, size, dst))

    def heartbeat_payload(self) -> dict:
        return {}

    def send_heartbeat(self) -> None:
        now = self.loop.now
        it = self.intent()
        p = {"caps": dict(self.body.caps), "pos": self.body.pos, "energy": self.body.energy,
             "busy": it.task_id if it else None, "t": now}
        p.update(self.heartbeat_payload())
        size = (96 + 24 * len(p.get("own", ())) + 12 * len(p.get("y", ())) + 8 * len(p.get("s", ()))
                + 64 * len(p.get("cat", ())))
        self.send("HB", p, size=size)

    def on_message(self, msg: Message) -> None:
        if not self.body.alive:
            return
        now = self.loop.now
        pi = self.peers.get(msg.src)
        if pi is None:
            pi = self.peers[msg.src] = PeerInfo(now, {}, (0, 0), 1.0, None, -1e9)
        pi.last_heard = now
        if msg.kind == "HB":
            p = msg.payload
            pi.caps, pi.pos, pi.energy, pi.busy, pi.report_time = dict(p["caps"]), p["pos"], p["energy"], p["busy"], p["t"]
        self.handle(msg, now)

    # ── views ────────────────────────────────────────────────────────
    def suspected(self, nid: str, now: float) -> bool:
        if nid == self.id:
            return False
        pi = self.peers.get(nid)
        return pi is None or (now - pi.last_heard) > self.cfg.fd_k * self.cfg.hb + 0.25

    def alive_view(self, now: float) -> List[str]:
        return sorted([self.id] + [n for n in self.peers if not self.suspected(n, now)])

    def swarm_view(self, now: float) -> List[CapabilityState]:
        out = [self.body.capability_state(now)]
        for n in self.alive_view(now):
            if n != self.id and self.peers[n].caps:
                out.append(CapabilityState(n, self.peers[n].report_time, dict(self.peers[n].caps)))
        return out

    def travel_cost(self, task: SimTask) -> float:
        return math.dist(self.body.pos, task.pos) / self.cfg.arena

    # ── hooks for subclasses ─────────────────────────────────────────
    def on_start(self) -> None: ...
    def on_tick(self, now: float) -> None: ...
    def handle(self, msg: Message, now: float) -> None: ...
    def on_task_discovered(self, task: SimTask, now: float) -> None: ...
    def intent(self) -> Optional[Intent]: ...


def best_feasible_tier(caps: dict, task: SimTask, now: float, max_tier: Optional[int] = None):
    """(tier index, quality) of the best tier a solo node satisfies, else (None, 0)."""
    from hesk.capabilities.matching import check_eligibility
    cs = CapabilityState("x", now, caps)
    tiers = task.defn.tiers if max_tier is None else task.defn.tiers[:max_tier + 1]
    for i, tier in enumerate(tiers):
        if check_eligibility(cs, tier.required):
            return i, tier.quality_estimate
    return None, 0.0
