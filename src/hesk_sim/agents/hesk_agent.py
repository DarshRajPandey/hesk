"""HESK runtime: the eight kernel algorithms wired into a message protocol.

Protocol (Contract-Net extended per Alg 004):
  ANN   announcer → all     task, epoch, tiers on offer
  BID   idle node → announcer  per-tier system cost (Alg 003 match + Alg 004 scarcity cost) + capability snapshot
  AWARD announcer → winner(s)  solo node or coalition (Alg 005), chosen tier (Alg 006 descent order)
  ACK / CANCEL
  HB    periodic heartbeat; carries ownership ledger entries (Alg 007 anti-entropy)

Ownership of each task is an EXCLUSIVE_OWNERSHIP ledger entry. Concurrent
owners (lost ACKs, partitions, divergent failure-detector views) are
resolved by the `reconcile` policy; "epoch" adds causal dominance in front
of Alg 008's progress → quality → time → id cascade, "kernel" calls Alg 008
exactly as implemented in hesk.ledger.reconciliation.

Ablation flags (AgentConfig.flags):
  scarcity, tiers, coalitions, upgrade, gossip : bool
  reconcile : "epoch" | "kernel" | "lww" | "none"
"""
from __future__ import annotations

import copy
from typing import Dict, List, Optional

from hesk.capabilities.matching import compute_full_match
from hesk.capabilities.model import CapabilityState
from hesk.coalitions.formation import LinkMetrics, form_coalition
from hesk.ledger.ledger import LocalStateLedger
from hesk.ledger.model import LedgerEntry, ObservationType, Provenance, StateSemanticType
from hesk.ledger.model import Conflict
from hesk.ledger.reconciliation import reconcile_full_ledger, resolve_exclusive_ownership
from hesk.tasks.allocation import compute_scarcity_penalty, compute_system_cost, evaluate_bids
from hesk.tasks.model import Bid

from hesk_sim.agents.base import AgentBase
from hesk_sim.network import Message
from hesk_sim.world import Intent

OWN = StateSemanticType.EXCLUSIVE_OWNERSHIP
BID_WINDOW = 0.35
AWARD_TIMEOUT = 1.0
RETRY_BACKOFF = 4.0
UPGRADE_PERIOD = 10.0
PROGRESS_HORIZON = 300.0

DEFAULT_FLAGS = dict(scarcity=True, tiers=True, coalitions=True, upgrade=True, gossip=True, reconcile="epoch",
                     coalition_scarcity=False, coalition_pen_max=0.5, lease=False, claims=False,
                     adapt_threshold=0.3, adaptive_timing=False)
CLAIM_MARGIN = 0.02      # a challenger must beat a live incumbent's score by this much
SWITCH_PERIOD = 5.0      # how often a busy drone reconsiders its claim
W_COST = 0.1             # score = priority × tier quality − W_COST × Alg-004 system cost


def _sig(v: Optional[dict]):
    if v is None:
        return None
    return v["sig"]


def _make_sig(v: dict) -> tuple:
    return (v["assignee"], tuple(v["members"]), v["tier"], v["epoch"], v["rev"], v["released"])


class HeskAgent(AgentBase):
    def on_start(self) -> None:
        f = dict(DEFAULT_FLAGS)
        f.update(self.cfg.flags)
        self.f = f
        self.ledger = LocalStateLedger(self.id)
        self.my: Optional[Intent] = None
        self.my_epoch = -1
        self.auction: Optional[dict] = None
        self.retry_at: Dict[str, float] = {}
        self.commit_until = 0.0
        self.next_upgrade = UPGRADE_PERIOD
        self.next_switch = 0.0
        self.dynamic: Dict[str, object] = {}
        self.stats = dict(conflicts=0, releases_by_reconcile=0, auctions=0, awards=0, coalitions=0)

    # ── ledger helpers ───────────────────────────────────────────────
    def own(self, tid: str) -> Optional[dict]:
        e = self.ledger.entries.get("own:" + tid)
        return e.value if e else None

    def set_own(self, tid: str, v: dict) -> None:
        v = dict(v)
        v["sig"] = _make_sig(v)  # version identity, computed once per write
        self.ledger.write_local("own:" + tid, v, OWN)

    def _entry(self, tid: str, v: dict, src: str) -> LedgerEntry:
        return LedgerEntry(key="own:" + tid, value=v, semantic_type=OWN, source_node=src,
                           lamport_clock=0, wall_time=v["ts"], confidence=1.0,
                           provenance=Provenance(origin=src, observation_type=ObservationType.RELAYED, original_clock=0))

    def _with_progress(self, v: dict, now: float) -> dict:
        v = dict(v)
        v["progress"] = 0.0 if v["released"] else min(1.0, max(0.0, (now - v["since"]) / PROGRESS_HORIZON))
        return v

    def merge(self, tid: str, remote: dict, src: str, now: float) -> None:
        local = self.own(tid)
        if _sig(local) == _sig(remote):
            return
        if local is None:
            self.set_own(tid, remote)
            self._after_merge(tid, now)
            return
        mode = self.f["reconcile"]
        if mode == "kernel":
            # Alg 008 exactly as implemented: progress → quality → earliest wall time → id.
            self.stats["conflicts"] += 1
            key = "own:" + tid
            self.ledger.entries[key].value = self._with_progress(local, now)
            reconcile_full_ledger(self.ledger, src, {key: self._entry(tid, self._with_progress(remote, now), src)})
            self._after_merge(tid, now)
            return
        if mode == "lww":
            winner = remote if (remote["ts"], remote["assignee"] or "") > (local["ts"], local["assignee"] or "") else local
        elif "score" in remote and "score" in local and remote["assignee"] != local["assignee"]:
            winner = self._claim_order(local, remote, now)
        elif remote["epoch"] != local["epoch"]:
            newer, older = (remote, local) if remote["epoch"] > local["epoch"] else (local, remote)
            winner = newer
            if self.f["lease"] and not newer.get("preempt") and self._lease_fresh(older, now):
                winner = older                  # live incumbent keeps its task: a suspicion is not a fact
        elif remote["assignee"] == local["assignee"]:
            winner = remote if remote["rev"] > local["rev"] else local
        elif mode == "none":
            winner = local
        else:  # "epoch": concurrent owners in the same epoch → Alg 008 cascade
            self.stats["conflicts"] += 1
            c = Conflict(key=tid, local_entry=self._entry(tid, self._with_progress(local, now), self.id),
                         remote_entry=self._entry(tid, self._with_progress(remote, now), src), semantic_type=OWN)
            res = resolve_exclusive_ownership(c)
            winner = remote if res.winning_value["assignee"] == remote["assignee"] else local
        if winner is remote:
            self.set_own(tid, remote)
            self._after_merge(tid, now)

    def _claim_order(self, local: dict, remote: dict, now: float) -> dict:
        """hesk4: deterministic order over competing claims (state-based, no handshake)."""
        if remote["epoch"] == local["epoch"]:
            ka = (local.get("score", -1e9), "" if local["released"] else "~", local["assignee"] or "")
            kb = (remote.get("score", -1e9), "" if remote["released"] else "~", remote["assignee"] or "")
            if local["released"] != remote["released"]:
                return local if remote["released"] else remote
            return remote if (kb[0], kb[1], tuple(-ord(c) for c in kb[2])) > (ka[0], ka[1], tuple(-ord(c) for c in ka[2])) else local
        newer, older = (remote, local) if remote["epoch"] > local["epoch"] else (local, remote)
        if older["released"] or not self._lease_fresh(older, now) or newer.get("preempt"):
            return newer
        if newer["released"]:
            return older
        return newer if newer.get("score", -1e9) > older.get("score", -1e9) + CLAIM_MARGIN else older

    def _claim_step(self, now: float) -> None:
        """hesk4: pick the best task I can claim and write the claim to my ledger; gossip does the rest."""
        busy = self.my is not None
        if busy and (len(self.my.members) > 1 or now < self.next_switch):
            return
        self.next_switch = now + SWITCH_PERIOD
        me = self.body.capability_state(now)
        swarm = self.swarm_view(now)
        cache: dict = {}
        cur_score = -1e9
        if busy:
            cur_score = (self.own(self.my.task_id) or {}).get("score", -1e9)
        best = None
        for tid, task in sorted(self.tasks.items()):
            if task.arrival > now or (busy and tid == self.my.task_id):
                continue
            v = self.own(tid)
            tiers = range(len(task.defn.tiers)) if self.f["tiers"] else [0]
            for ti in tiers:
                tier = task.defn.tiers[ti]
                mr = compute_full_match(me, tier.required, tier.preferred)
                if not mr.eligible:
                    continue
                pen = self._penalty(me, tier.required, swarm, cache)
                cost = compute_system_cost(mr.quality, self.body.energy, base_consumption=1.0, scarcity_penalty=pen,
                                           comm_cost=self.travel_cost(task), w_comm=1.0)
                score = task.defn.mission_priority * tier.quality_estimate - W_COST * cost
                if score <= 0:
                    break
                free = (v is None or v["released"] or not all(self._member_live(v, m, now) for m in v["members"]))
                if free or score > v.get("score", -1e9) + CLAIM_MARGIN:
                    gain = score - (cur_score + CLAIM_MARGIN if busy else 0.0)
                    if gain > 0 and (best is None or score > best[0]):
                        best = (score, tid, ti, mr.quality)
                break                           # best feasible tier only
        if best is None:
            return
        score, tid, ti, mq = best
        if busy:
            old = self.own(self.my.task_id)
            self.set_own(self.my.task_id, dict(old, released=True, rev=old["rev"] + 1, ts=now))
        v = self.own(tid)
        value = {"assignee": self.id, "members": [self.id], "tier": ti, "epoch": (v["epoch"] if v else 0) + 1,
                 "rev": 0, "released": False, "since": now, "ts": now, "match_quality": mq,
                 "lease": {self.id: now}, "preempt": False, "score": score}
        self.my = Intent(tid, ti, (self.id,))
        self.my_epoch = value["epoch"]
        self.set_own(tid, value)

    def _member_live(self, v: dict, m: str, now: float) -> bool:
        """Direct heartbeat OR a fresh lease relayed by anyone (indirect evidence)."""
        if not self.suspected(m, now):
            return True
        return self.f["lease"] and now - v["lease"].get(m, -1e9) <= self.cfg.fd_k * self.cfg.hb + 0.25

    def _lease_fresh(self, v: dict, now: float) -> bool:
        return (not v["released"]) and all(now - v["lease"].get(m, -1e9) <= self.cfg.fd_k * self.cfg.hb + 0.25
                                           for m in v["members"])

    def _after_merge(self, tid: str, now: float) -> None:
        v = self.own(tid)
        if self.my and self.my.task_id == tid:
            if v["released"] or self.id not in v["members"] or v["epoch"] != self.my_epoch:
                self.my = None                      # lost the ownership race → stand down
                self.stats["releases_by_reconcile"] += 1

    # ── heartbeat ────────────────────────────────────────────────────
    def heartbeat_payload(self) -> dict:
        if self.f["gossip"]:
            own = {k[4:]: e.value for k, e in self.ledger.entries.items()}  # values are never mutated in place
        else:  # only self-reported ownership
            own = {k[4:]: e.value for k, e in self.ledger.entries.items() if self.id in e.value["members"]}
        return {"own": own, "cat": list(self.dynamic.values())}

    # ── messaging ────────────────────────────────────────────────────
    def handle(self, msg: Message, now: float) -> None:
        p, k = msg.payload, msg.kind
        if k == "HB":
            for t in p.get("cat", ()):
                if t.id not in self.tasks:
                    self.tasks[t.id] = t
                    self.dynamic[t.id] = t
            entries = self.ledger.entries
            for tid, v in p.get("own", {}).items():
                e = entries.get("own:" + tid)
                if e is None or e.value["sig"] != v["sig"]:
                    self.merge(tid, v, msg.src, now)
                elif self.f["lease"] and v["lease"] != e.value["lease"]:
                    mine, theirs = e.value["lease"], v["lease"]   # lease renewals spread epidemically
                    if any(theirs[m] > mine[m] for m in theirs):
                        e.value = {**e.value, "lease": {m: max(mine[m], theirs[m]) for m in mine}}
        elif k == "ANN":
            self._on_announce(msg.src, p, now)
        elif k == "BID":
            a = self.auction
            if a and a["phase"] == "bid" and a["tid"] == p["tid"] and a["epoch"] == p["epoch"]:
                a["bids"][msg.src] = p
        elif k == "AWARD":
            self._on_award(msg.src, p, now)
        elif k == "ACK":
            a = self.auction
            if a and a["phase"] == "award" and a["tid"] == p["tid"] and a["epoch"] == p["epoch"]:
                a["acks"][msg.src] = p["ok"]
                self._check_acks(now)
        elif k == "CANCEL":
            if self.my and self.my.task_id == p["tid"] and self.my_epoch == p["epoch"]:
                self.my = None
                v = self.own(p["tid"])
                if v and v["epoch"] == p["epoch"] and self.id in v["members"]:
                    self.set_own(p["tid"], dict(v, released=True, rev=v["rev"] + 1, ts=now))

    def on_task_discovered(self, task, now: float) -> None:
        self.tasks[task.id] = task
        self.dynamic[task.id] = task

    # ── timing ───────────────────────────────────────────────────────
    def _bid_window(self) -> float:
        """hesk6: the bid window must cover a measured round trip, not a hard-coded constant."""
        if not self.f["adaptive_timing"]:
            return BID_WINDOW
        return max(BID_WINDOW, 2.5 * self.delay_p90() + 0.1)

    def _award_timeout(self) -> float:
        if not self.f["adaptive_timing"]:
            return AWARD_TIMEOUT
        return max(AWARD_TIMEOUT, 2.5 * self.delay_p90() + 0.2)

    def _commit_hold(self) -> float:
        if not self.f["adaptive_timing"]:
            return 2.0
        return max(2.0, 2 * self._bid_window() + 2.5 * self.delay_p90())

    # ── bidder side ──────────────────────────────────────────────────
    def _penalty(self, me, required, swarm, cache: dict) -> float:
        """Alg 004 scarcity penalty, memoised per required-dimension set within one evaluation."""
        if not self.f["scarcity"]:
            return 0.0
        key = frozenset(required)
        if key not in cache:
            cache[key] = compute_scarcity_penalty(me, set(required), swarm)
        return cache[key]

    def _bid_for(self, tid: str, tiers: List[int], now: float) -> Dict[int, list]:
        task = self.tasks[tid]
        me = self.body.capability_state(now)
        swarm = self.swarm_view(now)
        per = {}
        cache: dict = {}
        for ti in tiers:
            tier = task.defn.tiers[ti]
            pen = self._penalty(me, tier.required, swarm, cache)
            mr = compute_full_match(me, tier.required, tier.preferred)
            if not mr.eligible:
                per[ti] = [None, 0.0, pen]           # coalition candidate only
                continue
            cost = compute_system_cost(mr.quality, self.body.energy, base_consumption=1.0,
                                       scarcity_penalty=pen, comm_cost=self.travel_cost(task), w_comm=1.0)
            per[ti] = [cost, mr.quality, pen]
        return per

    def _on_announce(self, src: str, p: dict, now: float) -> None:
        tid = p["tid"]
        if tid not in self.tasks or self.my is not None or now < self.commit_until:
            return
        per = self._bid_for(tid, p["tiers"], now)
        if not self.f["coalitions"]:
            per = {ti: v for ti, v in per.items() if v[0] is not None}
            if not per:
                return
        self.commit_until = now + self._commit_hold()
        bid = {"tid": tid, "epoch": p["epoch"], "per": per, "caps": dict(self.body.caps), "energy": self.body.energy}
        self.send("BID", bid, size=48 + 16 * len(per) + 48, dst=src)

    def _on_award(self, src: str, p: dict, now: float) -> None:
        ok = self.my is None
        if ok:
            self.my = Intent(p["tid"], p["tier"], tuple(p["members"]))
            self.my_epoch = p["epoch"]
            self.set_own(p["tid"], p["value"])
        self.commit_until = 0.0
        if src == self.id:
            self.auction["acks"][self.id] = ok
        else:
            self.send("ACK", {"tid": p["tid"], "epoch": p["epoch"], "ok": ok}, size=32, dst=src)

    # ── announcer side ───────────────────────────────────────────────
    def _needs_auction(self, now: float) -> List[str]:
        out = []
        for tid, task in self.tasks.items():
            if task.arrival > now or self.retry_at.get(tid, 0.0) > now:
                continue
            v = self.own(tid)
            if v is None or v["released"]:
                out.append(tid)
            elif not all(self._member_live(v, m, now) for m in v["members"]):
                out.append(tid)
        out.sort(key=lambda t: (-self.tasks[t].defn.mission_priority, t))
        return out

    def _start_auction(self, tid: str, tiers: List[int], now: float, upgrade: bool = False) -> None:
        v = self.own(tid)
        epoch = (v["epoch"] if v else 0) + 1
        self.auction = {"tid": tid, "epoch": epoch, "tiers": tiers, "bids": {}, "acks": {},
                        "phase": "bid", "deadline": now + self._bid_window(), "upgrade": upgrade}
        self.stats["auctions"] += 1
        self.send("ANN", {"tid": tid, "epoch": epoch, "tiers": tiers}, size=48)
        if self.my is None and now >= self.commit_until:
            per = self._bid_for(tid, tiers, now)
            self.auction["bids"][self.id] = {"per": per, "caps": dict(self.body.caps), "energy": self.body.energy}
            self.commit_until = now + self._commit_hold()

    def _decide(self, now: float) -> None:
        a = self.auction
        task = self.tasks[a["tid"]]
        snaps = {n: CapabilityState(n, now, b["caps"]) for n, b in a["bids"].items()}
        for ti in a["tiers"]:
            solo = [Bid(a["tid"], n, b["per"][ti][0], b["per"][ti][1], b["energy"], snaps[n])
                    for n, b in a["bids"].items() if ti in b["per"] and b["per"][ti][0] is not None]
            if solo:
                res = evaluate_bids(solo, a["tid"])
                return self._award((res.assigned_node,), ti, res.match_quality, now)
            pool = sorted(snaps.values(), key=lambda s: s.node_id)
            if self.f["coalition_scarcity"]:
                # hesk2: Alg 004's scarcity guard applied to coalition recruits — a drone whose
                # scarce capabilities the tier does not use is not drafted as filler.
                pool = [s for s in pool if (a["bids"][s.node_id]["per"].get(ti) or [0, 0, 0])[2] < self.f["coalition_pen_max"]]
            if self.f["coalitions"] and len(pool) >= 2:
                cr = form_coalition(a["tid"], task.defn.tiers[ti].required, [], pool, LinkMetrics(), self.id)
                if cr.success:
                    self.stats["coalitions"] += 1
                    return self._award(tuple(sorted(cr.coalition.members)), ti, 0.5, now)
        self.retry_at[a["tid"]] = now + RETRY_BACKOFF
        self.auction = None
        if self.my is None:
            self.commit_until = 0.0

    def _award(self, members: tuple, tier: int, mq: float, now: float) -> None:
        a = self.auction
        a["phase"], a["deadline"], a["members"] = "award", now + self._award_timeout(), members
        value = {"assignee": "+".join(members), "members": list(members), "tier": tier, "epoch": a["epoch"],
                 "rev": 0, "released": False, "since": now, "ts": now, "match_quality": mq,
                 "lease": {m: now for m in members}, "preempt": a["upgrade"]}
        a["value"] = value
        payload = {"tid": a["tid"], "epoch": a["epoch"], "tier": tier, "members": list(members), "value": value}
        for m in members:
            if m == self.id:
                self._on_award(self.id, payload, now)
            else:
                self.send("AWARD", payload, size=96, dst=m)
        self._check_acks(now)

    def _check_acks(self, now: float) -> None:
        a = self.auction
        if a is None or a["phase"] != "award":
            return
        if any(ok is False for ok in a["acks"].values()):
            return self._abort(now, backoff=0.5)
        if all(a["acks"].get(m) for m in a["members"]):
            self.set_own(a["tid"], a["value"])
            self._after_merge(a["tid"], now)        # an upgrade may have displaced the announcer itself
            self.stats["awards"] += 1
            self.auction = None

    def _abort(self, now: float, backoff: float) -> None:
        a = self.auction
        for m, ok in a["acks"].items():
            if ok:
                if m == self.id:
                    self.handle(Message("CANCEL", self.id, {"tid": a["tid"], "epoch": a["epoch"]}), now)
                else:
                    self.send("CANCEL", {"tid": a["tid"], "epoch": a["epoch"]}, size=32, dst=m)
        self.retry_at[a["tid"]] = now + backoff
        self.auction = None

    # ── periodic logic ───────────────────────────────────────────────
    def on_tick(self, now: float) -> None:
        self._self_check(now)
        a = self.auction
        if a is not None:
            if now >= a["deadline"]:
                if a["phase"] == "bid":
                    self._decide(now)
                else:
                    self._abort(now, backoff=1.0)
            return
        claims = self.f["claims"]
        if claims == "adaptive":
            # hesk5: transactional auctions (coalitions possible) while the channel is good,
            # state-based claims once the locally measured loss passes the crossover.
            claims = self.estimated_loss(now) > self.f["adapt_threshold"]
        if claims:
            self._claim_step(now)
        if self.alive_view(now)[0] != self.id:
            return                              # not the responsible announcer in my view
        pending = [] if claims else self._needs_auction(now)
        if pending:
            tid = pending[0]
            n = len(self.tasks[tid].defn.tiers)
            return self._start_auction(tid, list(range(n)) if self.f["tiers"] else [0], now)
        if self.f["upgrade"] and self.f["tiers"] and now >= self.next_upgrade:
            self.next_upgrade = now + UPGRADE_PERIOD
            idle = [n for n in self.alive_view(now) if n != self.id and self.peers[n].busy is None]
            if self.my is None:
                idle.append(self.id)
            if not idle:
                return
            degraded = [(tid, v) for tid in sorted(self.tasks) if (v := self.own(tid)) and not v["released"] and v["tier"] > 0]
            degraded.sort(key=lambda x: (-self.tasks[x[0]].defn.mission_priority, x[0]))
            if degraded:
                tid, v = degraded[0]
                self._start_auction(tid, list(range(v["tier"])), now, upgrade=True)

    def _self_check(self, now: float) -> None:
        """Alg 006 triggers observed locally: own capability loss, coalition member loss."""
        if self.my is None:
            return
        tid = self.my.task_id
        v = self.own(tid)
        if v is None:
            return
        if v["epoch"] != self.my_epoch or tuple(v["members"]) != self.my.members:
            self.my = None              # my ledger records a different assignment: I no longer own this task
            return
        if self.f["lease"] and not v["released"] and self.id in v["members"]:
            e = self.ledger.entries["own:" + tid]
            e.value = v = {**v, "lease": {**v["lease"], self.id: now}}
        if len(self.my.members) > 1:
            if not all(self._member_live(v, m, now) for m in self.my.members):
                self.my = None
                self.set_own(tid, dict(v, released=True, rev=v["rev"] + 1, ts=now))
            return
        task = self.tasks[tid]
        me = self.body.capability_state(now)
        tier = task.defn.tiers[self.my.tier]
        if compute_full_match(me, tier.required, tier.preferred).eligible:
            return
        if self.f["tiers"]:
            for ti in range(self.my.tier + 1, len(task.defn.tiers)):
                t2 = task.defn.tiers[ti]
                if compute_full_match(me, t2.required, t2.preferred).eligible:
                    self.my = Intent(tid, ti, self.my.members)
                    self.set_own(tid, dict(v, tier=ti, rev=v["rev"] + 1, ts=now))
                    return
        self.my = None
        self.set_own(tid, dict(v, released=True, rev=v["rev"] + 1, ts=now))

    def intent(self) -> Optional[Intent]:
        return self.my
