"""Ground truth, physics-lite movement, fault injection and scoring.

Invariant (from the HESK README): agents never read this module's state
except their *own* body through `Body`. The world reads agents' declared
intents only to move them and to score the run.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from hesk.capabilities.matching import check_eligibility
from hesk.capabilities.model import CapabilityState
from hesk.coalitions.formation import compose_capabilities
from hesk.core.types import PriorityClass

from hesk_sim.engine import EventLoop, RngStreams
from hesk_sim.network import Network
from hesk_sim.scenario import ScenarioConfig, SimTask, NodeSpec, generate

SCORE_DT = 0.5


@dataclass
class Intent:
    task_id: str
    tier: int
    members: Tuple[str, ...]  # sorted, includes self; len>1 => coalition


class Body:
    """The only window an agent has onto ground truth: itself."""

    def __init__(self, spec: NodeSpec):
        self.node_id = spec.node_id
        self.archetype = spec.archetype
        self.caps = dict(spec.caps)
        self.pos = spec.pos
        self.energy = 1.0
        self.alive = True

    def capability_state(self, now: float) -> CapabilityState:
        return CapabilityState(node_id=self.node_id, timestamp=now, dimensions=dict(self.caps))


@dataclass
class RunMetrics:
    utility: float = 0.0
    utility_ideal: float = 0.0
    critical_utility: float = 0.0
    critical_ideal: float = 0.0
    tier0_seconds: float = 0.0
    task_seconds_covered: float = 0.0
    task_seconds_total: float = 0.0
    coalition_seconds: float = 0.0
    duplicate_agent_seconds: float = 0.0
    invalid_claim_seconds: float = 0.0   # agent on station claiming a task it cannot truly serve
    recoveries: List[float] = field(default_factory=list)
    unrecovered: int = 0
    timeline: List[float] = field(default_factory=list)  # utility rate sampled every 5 s


class World:
    def __init__(self, cfg: ScenarioConfig, seed: int):
        self.cfg = cfg
        self.rngs = RngStreams(seed)
        self.loop = EventLoop()
        self.net = Network(self.loop, self.rngs.get("net"), loss=cfg.loss, burst_len=cfg.burst_len,
                           latency=cfg.latency, jitter=cfg.jitter, jam=cfg.jam)
        self.node_specs, self.tasks = generate(cfg, self.rngs.get("layout"))
        self.bodies: Dict[str, Body] = {s.node_id: Body(s) for s in self.node_specs}
        self.task_by_id: Dict[str, SimTask] = {t.id: t for t in self.tasks}
        self.agents: Dict[str, object] = {}
        self.m = RunMetrics()
        self._pending_recovery: List[Tuple[str, float, float]] = []  # (task, q_before, t_kill)
        self._last_q: Dict[str, float] = {}
        self._last_groups: Dict[str, Tuple[str, ...]] = {}
        self._acc_rate = 0.0
        self.events: List[Tuple[float, str, str]] = []

    # ── setup ────────────────────────────────────────────────────────
    def attach(self, agents: Dict[str, object]) -> None:
        self.agents = agents
        for nid, a in agents.items():
            self.net.register(nid, a.on_message)
        self._schedule_faults()
        initial = [t for t in self.tasks if t.arrival <= 0.0]
        for a in agents.values():
            a.start(self.loop, self.net, initial)
        for t in self.tasks:
            if t.arrival > 0.0:
                self.loop.at(t.arrival, lambda t=t: self._task_arrives(t))
        self.loop.at(SCORE_DT, self._score_step)

    def _task_arrives(self, task: SimTask) -> None:
        # The nearest live drone "detects" the new task with its own sensors.
        alive = [b for b in self.bodies.values() if b.alive]
        if not alive:
            return
        d = min(alive, key=lambda b: (math.dist(b.pos, task.pos), b.node_id))
        self.agents[d.node_id].on_task_discovered(task, self.loop.now)

    # ── faults ───────────────────────────────────────────────────────
    def _schedule_faults(self) -> None:
        cfg, rng = self.cfg, self.rngs.get("faults")
        n_kill = int(round(cfg.kill_frac * cfg.n_nodes))
        if n_kill:
            t0, t1 = cfg.kill_window
            times = sorted(rng.uniform(t0, t1) for _ in range(n_kill))
            for t in times:
                self.loop.at(t, lambda: self._kill_one(rng))
        for (p0, p1, k) in cfg.partitions:
            self.loop.at(p0, lambda k=k: self._partition(k, rng))
            self.loop.at(p1, self._heal)
        for _ in range(cfg.n_degrade):
            t = rng.uniform(*cfg.degrade_window)
            self.loop.at(t, lambda: self._degrade_one(rng))

    def _kill_one(self, rng) -> None:
        alive = sorted(n for n, b in self.bodies.items() if b.alive)
        if len(alive) <= 1:
            return
        mode = self.cfg.kill_mode
        if mode == "leader":            # adversary decapitates: lowest id = coordinator in leader-based schemes
            victim = alive[0]
        elif mode == "scarce":          # adversary hunts rare platforms first
            rarity = {"thermal": 0, "gpu": 1, "lidar": 2, "relay": 3, "eo": 4, "scout": 5}
            victim = min(alive, key=lambda n: (rarity[self.bodies[n].archetype], rng.random()))
        elif mode == "busy":            # adversary shoots whoever is serving the highest-value task
            best = max(alive, key=lambda n: (self._contribution(n), rng.random()))
            victim = best
        else:
            victim = rng.choice(alive)
        self.kill(victim)

    def _contribution(self, nid: str) -> float:
        for tid, grp in self._last_groups.items():
            if nid in grp:
                return self.task_by_id[tid].defn.mission_priority * self._last_q.get(tid, 0.0)
        return 0.0

    def kill(self, nid: str) -> None:
        b = self.bodies[nid]
        if not b.alive:
            return
        b.alive = False
        self.net.alive[nid] = False
        self.events.append((self.loop.now, "kill", nid))
        for tid, grp in self._last_groups.items():
            if nid in grp and self._last_q.get(tid, 0) > 0:
                self._pending_recovery.append((tid, self._last_q[tid], self.loop.now))

    def _partition(self, k: int, rng) -> None:
        ids = sorted(self.bodies)
        if self.cfg.partition_mode == "spatial":
            ids.sort(key=lambda n: self.bodies[n].pos[0])
            groups = [ids[i * len(ids) // k:(i + 1) * len(ids) // k] for i in range(k)]
        else:
            rng.shuffle(ids)
            groups = [ids[i::k] for i in range(k)]
        self.net.set_partition(groups)
        self.events.append((self.loop.now, "partition", str(k)))

    def _heal(self) -> None:
        self.net.heal()
        self.events.append((self.loop.now, "heal", ""))

    def _degrade_one(self, rng) -> None:
        alive = sorted(n for n, b in self.bodies.items() if b.alive)
        if not alive:
            return
        b = self.bodies[rng.choice(alive)]
        if b.caps["has_thermal"]:
            b.caps["has_thermal"] = False
        elif b.caps["has_lidar"]:
            b.caps["has_lidar"] = False
        b.caps["compute"] = round(b.caps["compute"] * 0.25, 2)
        b.caps["sensing_visual"] = round(b.caps["sensing_visual"] * 0.7, 3)
        self.events.append((self.loop.now, "degrade", b.node_id))

    # ── movement + scoring ───────────────────────────────────────────
    def _score_step(self) -> None:
        now, cfg, m = self.loop.now, self.cfg, self.m
        claims: Dict[str, Dict[Tuple[Tuple[str, ...], int], List[str]]] = {}
        for nid, b in self.bodies.items():
            if not b.alive:
                continue
            it: Optional[Intent] = self.agents[nid].intent()
            b.energy = max(0.0, b.energy - SCORE_DT / 2400.0)
            if it is None or it.task_id not in self.task_by_id:
                continue
            task = self.task_by_id[it.task_id]
            dx, dy = task.pos[0] - b.pos[0], task.pos[1] - b.pos[1]
            d = math.hypot(dx, dy)
            step = cfg.speed * SCORE_DT
            if d > cfg.station_radius:
                f = min(1.0, step / d)
                b.pos = (b.pos[0] + dx * f, b.pos[1] + dy * f)
                b.energy = max(0.0, b.energy - SCORE_DT / 2400.0)
                continue
            claims.setdefault(it.task_id, {}).setdefault((it.members, it.tier), []).append(nid)

        groups_now: Dict[str, Tuple[str, ...]] = {}
        q_now: Dict[str, float] = {}
        rate = 0.0
        for task in self.tasks:
            if task.arrival > now:
                continue
            p = task.defn.mission_priority
            crit = task.defn.priority_class == PriorityClass.CRITICAL
            m.utility_ideal += p * SCORE_DT
            m.task_seconds_total += SCORE_DT
            if crit:
                m.critical_ideal += p * SCORE_DT
            best_q, best_grp, best_tier = 0.0, None, None
            on_station = 0
            for (members, tier), present in claims.get(task.id, {}).items():
                on_station += len(present)
                if len(present) != len(members):          # coalition not yet assembled
                    continue
                if tier >= len(task.defn.tiers):
                    continue
                req = task.defn.tiers[tier].required
                states = [self.bodies[n].capability_state(now) for n in members]
                if len(states) == 1:
                    ok = check_eligibility(states[0], req)
                else:
                    comp = compose_capabilities(states, req)
                    ok = check_eligibility(CapabilityState("C", now, comp.composed_values), req)
                if not ok:
                    m.invalid_claim_seconds += len(present) * SCORE_DT
                    continue
                q = task.defn.tiers[tier].quality_estimate
                if q > best_q:
                    best_q, best_grp, best_tier = q, members, tier
            if best_grp is not None:
                m.utility += p * best_q * SCORE_DT
                rate += p * best_q
                m.task_seconds_covered += SCORE_DT
                if crit:
                    m.critical_utility += p * best_q * SCORE_DT
                if best_tier == 0:
                    m.tier0_seconds += SCORE_DT
                if len(best_grp) > 1:
                    m.coalition_seconds += SCORE_DT
                m.duplicate_agent_seconds += max(0, on_station - len(best_grp)) * SCORE_DT
                groups_now[task.id] = best_grp
            q_now[task.id] = best_q

        still = []
        for (tid, q_before, t_kill) in self._pending_recovery:
            if q_now.get(tid, 0.0) >= q_before - 1e-9:
                m.recoveries.append(now - t_kill)
            else:
                still.append((tid, q_before, t_kill))
        self._pending_recovery = still
        self._last_groups, self._last_q = groups_now, q_now
        self._acc_rate += rate
        if int(round(now / SCORE_DT)) % int(5.0 / SCORE_DT) == 0:
            m.timeline.append(round(self._acc_rate / (5.0 / SCORE_DT), 4))
            self._acc_rate = 0.0
        if now + SCORE_DT <= cfg.duration + 1e-9:
            self.loop.at(now + SCORE_DT, self._score_step)

    def run(self) -> dict:
        t0 = time.perf_counter()
        self.loop.run_until(self.cfg.duration)
        wall = time.perf_counter() - t0
        m, st = self.m, self.net.stats
        m.unrecovered = len(self._pending_recovery)
        alive = sum(b.alive for b in self.bodies.values())
        rec = sorted(m.recoveries)
        n_rec_events = len(rec) + m.unrecovered
        return {
            "utility_ratio": m.utility / m.utility_ideal if m.utility_ideal else 0.0,
            "critical_ratio": m.critical_utility / m.critical_ideal if m.critical_ideal else 0.0,
            "coverage": m.task_seconds_covered / m.task_seconds_total if m.task_seconds_total else 0.0,
            "tier0_share": m.tier0_seconds / m.task_seconds_covered if m.task_seconds_covered else 0.0,
            "coalition_share": m.coalition_seconds / m.task_seconds_covered if m.task_seconds_covered else 0.0,
            "duplicate_agent_s": m.duplicate_agent_seconds,
            "invalid_claim_s": m.invalid_claim_seconds,
            "recovery_median_s": rec[len(rec) // 2] if rec else None,
            "recovered_frac": len(rec) / n_rec_events if n_rec_events else None,
            "messages": st.tx,
            "bytes": st.tx_bytes,
            "msgs_per_node_s": st.tx / (self.cfg.n_nodes * self.cfg.duration),
            "deliveries": st.deliveries,
            "alive_end": alive,
            "wall_s": wall,
            "timeline": m.timeline,
        }
