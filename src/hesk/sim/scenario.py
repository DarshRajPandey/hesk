"""One simulated partition-and-heal episode, scored against ground truth.

Timeline (virtual seconds)::

    [0, t_connected)                      all nodes connected; causal ownership handoffs,
                                          counters, observations, resource reports
    [t_connected, t_connected+t_part)     network splits into ``n_groups`` groups; concurrent
                                          ownership claims on previously-owned keys
    [heal, heal+t_settle)                 network heals; gossip until the horizon

Workload and network randomness are drawn from independent, seed-derived streams *before*
the run, so every implementation faces exactly the same workload and the same message
fates; only the replica logic differs.
"""
from __future__ import annotations

import heapq
import math
import random
from dataclasses import asdict, dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from hesk.core import clock
from hesk.sim.replicas import Replica

ReplicaFactory = Callable[[str], Replica]


@dataclass(frozen=True)
class Params:
    n_nodes: int = 12
    n_groups: int = 3
    claimants: int = 4            # concurrent claimants per contested key
    claim_spread: float = 0.05    # std-dev of claimants' progress (the legacy epsilon is 0.05)
    chain_restart: bool = False   # True: successors restart at low progress (reassignment after loss)
    one_per_group: bool = True    # True: at most one claimant per partition group (what the allocation
                                  # layer guarantees inside a connected component); False: stress test
    handoff_gap: float = 2.0      # seconds a node waits after seeing a claim before taking over
    clock_skew: float = 0.1       # std-dev of per-node clock offset (s)
    loss: float = 0.05
    dup: float = 0.02
    latency: float = 0.15
    jitter: float = 0.10
    period: float = 1.0           # gossip period
    fanout: int = 2
    t_connected: float = 20.0
    t_part: float = 15.0
    t_settle: float = 30.0
    n_chain: int = 4
    chain_len: int = 4
    n_contest: int = 6
    n_counter: int = 3
    n_obs: int = 3
    n_res: int = 3
    incs_per_node: int = 6
    obs_per_node: int = 6
    res_observers: int = 3
    res_period: float = 1.5
    crash_frac: float = 0.0       # fraction of nodes that crash-stop at a random time during the mission
    split: str = "even"           # even | majority (first group holds a strict majority of nodes)
    max_units: int = 2_000        # abort guard: payload-size proxy (see Replica.units); legit payloads are < 20

    @property
    def heal(self) -> float:
        return self.t_connected + self.t_part

    @property
    def horizon(self) -> float:
        return self.heal + self.t_settle


def _rng(seed: int, stream: str) -> random.Random:
    # string seeds are hashed with sha512 -> identical across processes / PYTHONHASHSEED
    return random.Random(f"hesk:{seed}:{stream}")


class World:
    """What an *idealised* consensus layer is allowed to know: who is reachable and alive.

    Used only by the quorum baseline, and deliberately generous to it: leader election is
    instantaneous and failure detection perfect; a write commits iff the writer's side of the
    network holds a majority of the configured cluster and enough acks survive packet loss.
    """

    def __init__(self, p: Params, nodes, group_of, crash_at, rng: random.Random):
        self.p, self.nodes, self.group_of, self.crash_at, self.rng = p, nodes, group_of, crash_at, rng
        self.t = 0.0
        self.log: Dict[str, Any] = {}

    def alive(self, n: str) -> bool:
        return self.t < self.crash_at[n]

    def commit_ok(self, node: str, attempts: int = 3) -> bool:
        p = self.p
        partitioned = p.t_connected <= self.t < p.heal
        peers = [m for m in self.nodes if m != node and self.alive(m)
                 and (not partitioned or self.group_of[m] == self.group_of[node])]
        need = len(self.nodes) // 2 + 1 - 1  # acks needed besides the writer itself
        ack_p = (1 - p.loss) ** 2  # request and reply must both survive
        for _ in range(attempts):
            if sum(self.rng.random() < ack_p for _ in peers) >= need:
                return True
        return False


def run_scenario(params: Params, make_replica: ReplicaFactory, seed: int) -> Dict[str, Any]:
    p = params
    rn, rt = _rng(seed, "network"), _rng(seed, "topology")
    nodes = [f"n{i:02d}" for i in range(p.n_nodes)]
    skew = {n: rt.gauss(0.0, p.clock_skew) for n in nodes}
    order = nodes[:]
    rt.shuffle(order)
    if p.split == "majority" and p.n_groups > 1:
        big = p.n_nodes // 2 + 1
        group_of = {n: (0 if i < big else 1 + (i - big) % (p.n_groups - 1)) for i, n in enumerate(order)}
    else:
        group_of = {n: i % p.n_groups for i, n in enumerate(order)}
    rc_ = _rng(seed, "crash")
    victims = set(rc_.sample(nodes, int(round(p.crash_frac * p.n_nodes)))) if p.crash_frac > 0 else set()
    crash_at = {n: (rc_.uniform(0.5 * p.t_connected, p.heal) if n in victims else math.inf) for n in nodes}
    replicas = {n: make_replica(n) for n in nodes}
    world = World(p, nodes, group_of, crash_at, _rng(seed, "quorum"))
    for r in replicas.values():
        if hasattr(r, "attach"):
            r.attach(world)

    def reachable(a: str, b: str, t: float) -> bool:
        return not (p.t_connected <= t < p.heal) or group_of[a] == group_of[b]

    q: List[Tuple[float, int, str, tuple]] = []
    ctr = [0]

    def push(t: float, kind: str, *data: Any) -> None:
        ctr[0] += 1
        heapq.heappush(q, (t, ctr[0], kind, data))

    # ── ground truth, filled in as ops execute ──
    truth: Dict[str, Any] = {"chain": {}, "contest_max": {}, "ctr": {}, "obs": {}, "res": {}, "res_t": {}, "own_attempts": 0, "own_accepted": 0, "contest_accepted": {}}
    token = [0]

    def next_token() -> int:
        token[0] += 1
        return token[0]

    chain_keys = [f"own:chain{i}" for i in range(p.n_chain)]
    contest_keys = [f"own:contest{i}" for i in range(p.n_contest)]
    ctr_keys = [f"ctr:{i}" for i in range(p.n_counter)]
    obs_keys = [f"obs:{i}" for i in range(p.n_obs)]
    res_keys = [f"res:{i}" for i in range(p.n_res)]

    # chains: causal handoffs while connected
    rc = _rng(seed, "workload:chain")
    for k in chain_keys:
        seq = rc.sample(nodes, min(p.chain_len, p.n_nodes))
        push(rc.uniform(1.0, 3.0), "claim", seq[0], k, 0.60 if p.chain_restart else 0.10, 0.8, "chain")
        for j in range(1, len(seq)):
            push(rc.uniform(3.0, 4.0), "handoff", k, seq, j)
    # contested keys: prior owner while connected, then concurrent claims inside the partition
    rk = _rng(seed, "workload:contest")
    for k in contest_keys:
        prior = rk.choice(nodes)
        push(rk.uniform(1.0, 3.0), "claim", prior, k, 0.40, 0.8, "prior")
        if p.one_per_group:
            gids = rk.sample(range(p.n_groups), min(p.claimants, p.n_groups))
            claimants = [rk.choice([n for n in nodes if group_of[n] == g]) for g in gids]
        else:
            claimants = rk.sample(nodes, min(p.claimants, p.n_nodes))
        for n in claimants:
            prog = min(1.0, max(0.0, rk.gauss(0.5, p.claim_spread)))
            push(p.t_connected + rk.uniform(0.5, 2.0), "claim", n, k, prog, rk.uniform(0.2, 1.0), "contest")
    t_end_ops = p.heal
    ri, ro = _rng(seed, "workload:counter"), _rng(seed, "workload:obs")
    for n in nodes:
        for _ in range(p.incs_per_node if ctr_keys else 0):
            push(ri.uniform(1.0, t_end_ops), "inc", n, ri.choice(ctr_keys))
        for _ in range(p.obs_per_node if obs_keys else 0):
            push(ro.uniform(1.0, t_end_ops), "obs", n, ro.choice(obs_keys))
    rr = _rng(seed, "workload:resource")
    for k in res_keys:
        for n in rr.sample(nodes, min(p.res_observers, p.n_nodes)):
            t = rr.uniform(1.0, 1.0 + p.res_period)
            while t < t_end_ops:
                push(t, "res", n, k)
                t += p.res_period * rr.uniform(0.7, 1.3)

    # gossip: fully pre-drawn schedule -> message fates independent of replica behaviour
    for n in nodes:
        t = rn.uniform(0.0, p.period)
        while t < p.horizon:
            peers = rn.sample([m for m in nodes if m != n], min(p.fanout, p.n_nodes - 1))
            fates = [(rn.random() < p.loss, p.latency + rn.uniform(0, p.jitter),
                      rn.random() < p.dup, p.latency + rn.uniform(0, 3 * p.jitter)) for _ in peers]
            push(t, "tick", n, tuple(zip(peers, fates)))
            t += p.period
    t = p.heal
    while t <= p.horizon:
        push(t, "check")
        t += 0.5

    # Perfect failure detector (most favourable to the reconnection path): every cross-group link
    # is marked 'partitioned' at the split and the first delivery after the heal is flagged.
    needs_reconcile = {(a, b) for a in nodes for b in nodes if group_of[a] != group_of[b]}
    stable_since: Dict[str, Optional[float]] = {c: None for c in ("own", "ctr", "obs", "res")}
    delivered = 0
    max_units_seen = 0
    aborted = False

    def at(node: str, t: float):
        return clock.use_clock(lambda: t + skew[node])

    def digest(cls: str, rep: Replica) -> tuple:
        if cls == "own":
            return tuple((rep.read_owner(k) or (None,))[0] for k in chain_keys + contest_keys)
        if cls == "ctr":
            return tuple(rep.read_counter(k) for k in ctr_keys)
        if cls == "obs":
            return tuple(tuple(sorted(rep.read_obs(k)[0])) for k in obs_keys)
        return tuple(rep.read_resource(k) for k in res_keys)

    def alive(n: str, t: float) -> bool:
        return t < crash_at[n]

    def do_claim(n: str, k: str, prog: float, qual: float, t: float) -> bool:
        world.t = t
        truth["own_attempts"] += 1
        with at(n, t):
            ok = replicas[n].claim(k, n, prog, qual)
        ok = ok is None or bool(ok)  # replicas that cannot refuse return None
        truth["own_accepted"] += int(ok)
        return ok

    while q:
        t, _, kind, d = heapq.heappop(q)
        world.t = t
        if kind in ("claim", "inc", "obs", "res", "tick") and not alive(d[0], t):
            continue
        if kind == "claim":
            n, k, prog, qual, role = d
            if not do_claim(n, k, prog, qual, t):
                continue
            if role == "contest":
                truth["contest_max"][k] = max(truth["contest_max"].get(k, 0.0), prog)
                truth["contest_accepted"][k] = truth["contest_accepted"].get(k, 0) + 1
            elif role == "chain":
                truth["chain"][k] = n
        elif kind == "handoff":
            k, seq, j = d
            if j == 1:  # arms the retry loop; later hops are chained from "try"
                push(t, "try", k, seq, 1, t + p.handoff_gap, p.t_connected - p.handoff_gap)
        elif kind == "try":
            k, seq, j, due, deadline = d
            if j >= len(seq) or t > deadline:
                continue
            n = seq[j]
            if not alive(n, t):
                continue
            if t < due:
                push(due, "try", k, seq, j, due, deadline)
                continue
            seen = replicas[n].read_owner(k)
            if seen is not None and seen[0] == seq[j - 1] and do_claim(n, k, 0.10 if p.chain_restart else 0.10 + 0.10 * j, 0.8, t):
                truth["chain"][k] = n
                push(t + p.handoff_gap, "try", k, seq, j + 1, t + p.handoff_gap, deadline)
            else:
                push(t + 0.25, "try", k, seq, j, due, deadline)
        elif kind == "inc":
            n, k = d
            with at(n, t):
                replicas[n].increment(k)
            truth["ctr"][k] = truth["ctr"].get(k, 0) + 1
        elif kind == "obs":
            n, k = d
            tok = next_token()
            with at(n, t):
                replicas[n].observe(k, tok)
            truth["obs"].setdefault(k, []).append(tok)
        elif kind == "res":
            n, k = d
            tok = next_token()
            with at(n, t):
                replicas[n].report(k, tok)
            truth["res"][k] = tok
            truth["res_t"][tok] = t
        elif kind == "tick":
            n, sends = d
            with at(n, t):
                payload = replicas[n].snapshot()
            for peer, (lost, lat, dup, dlat) in sends:
                if lost or not reachable(n, peer, t) or not alive(peer, t):
                    continue
                push(t + lat, "deliver", n, peer, payload)
                if dup:
                    push(t + dlat, "deliver", n, peer, payload)
        elif kind == "deliver":
            src, dst, payload = d
            if not alive(dst, t):
                continue
            u = replicas[dst].units(payload)
            max_units_seen = max(max_units_seen, u)
            if u > p.max_units:
                aborted = True
                break
            reconnected = t >= p.heal and (dst, src) in needs_reconcile
            needs_reconcile.discard((dst, src))
            delivered += 1
            with at(dst, t):
                replicas[dst].receive(replicas[dst].clone_payload(payload), src, reconnected)
        elif kind == "check":
            live = [n for n in nodes if alive(n, t)]
            for cls in stable_since:
                ds = {digest(cls, replicas[n]) for n in live}
                if len(ds) == 1:
                    if stable_since[cls] is None:
                        stable_since[cls] = t
                else:
                    stable_since[cls] = None

    live = [n for n in nodes if crash_at[n] == math.inf]
    out = _score(p, live, replicas, truth, chain_keys, contest_keys, ctr_keys, obs_keys, res_keys,
                 stable_since, delivered, digest)
    out["aborted"] = int(aborted)
    out["own_accept"] = truth["own_accepted"] / truth["own_attempts"] if truth["own_attempts"] else None
    if contest_keys:
        acc = [truth["contest_accepted"].get(k, 0) for k in contest_keys]
        out["contest_orphan"] = sum(a == 0 for a in acc) / len(acc)          # reassigned task nobody could take
        out["contest_dup"] = sum(max(0, a - 1) for a in acc) / len(acc)      # extra concurrent executors
    else:
        out["contest_orphan"] = out["contest_dup"] = None
    out["live_nodes"] = len(live)
    out["max_units"] = max_units_seen
    return out


def _score(p, nodes, replicas, truth, chain_keys, contest_keys, ctr_keys, obs_keys, res_keys,
           stable_since, delivered, digest) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    nrep = len(nodes)

    present = {"own": p.n_chain + p.n_contest, "ctr": p.n_counter, "obs": p.n_obs, "res": p.n_res}
    for cls in ("own", "ctr", "obs", "res"):
        if not present[cls]:
            out[f"conv_{cls}"] = out[f"t_conv_{cls}"] = None
            continue
        ds = {digest(cls, replicas[n]) for n in nodes}
        out[f"conv_{cls}"] = int(len(ds) == 1)
        s = stable_since[cls]
        out[f"t_conv_{cls}"] = (s - p.heal) if (s is not None and len(ds) == 1) else None
    out["conv_all"] = int(all(out[f"conv_{c}"] for c in present if present[c]))

    # ownership: causal chains (should be unambiguous) and concurrent contests
    stale = tot = 0
    split_chain = 0
    for k in chain_keys:
        if k not in truth["chain"]:
            continue
        views = [replicas[n].read_owner(k) for n in nodes]
        owners = {v[0] if v else None for v in views}
        split_chain += int(len(owners) > 1)
        for v in views:
            tot += 1
            stale += int((v[0] if v else None) != truth["chain"][k])
    out["chain_stale"] = stale / tot if tot else None
    out["chain_split"] = split_chain / max(1, len([k for k in chain_keys if k in truth["chain"]])) if tot else None

    regrets, splits = [], 0
    for k in contest_keys:
        views = [replicas[n].read_owner(k) for n in nodes]
        splits += int(len({v[0] if v else None for v in views}) > 1)
        if k not in truth["contest_max"]:
            continue  # no claim was accepted (e.g. refused by a quorum): regret is undefined
        best = truth["contest_max"][k]
        regrets.extend(best - (v[1] if v else 0.0) for v in views)
    out["contest_split"] = splits / len(contest_keys) if contest_keys else None
    out["contest_regret"] = sum(regrets) / len(regrets) if regrets else None

    loss = []
    for k in ctr_keys:
        tv = truth["ctr"].get(k, 0)
        for n in nodes:
            loss.append(max(0.0, 1 - replicas[n].read_counter(k) / tv) if tv else 0.0)
    out["ctr_loss"] = sum(loss) / len(loss) if loss else None

    dup_num = dup_den = 0
    recall = []
    for k in obs_keys:
        ideal = set(sorted(truth["obs"].get(k, []))[-5:])
        for n in nodes:
            distinct, entries = replicas[n].read_obs(k)
            dup_num += entries - len(distinct)
            dup_den += entries
            recall.append(len(distinct & ideal) / max(1, len(ideal)))
    out["obs_dup"] = (dup_num / dup_den if dup_den else 0.0) if obs_keys else None
    out["obs_recall"] = sum(recall) / len(recall) if recall else None

    wrong = tot = old = 0
    lags: List[float] = []
    for k in res_keys:
        newest_t = truth["res_t"].get(truth["res"].get(k), 0.0)
        for n in nodes:
            tot += 1
            held = replicas[n].read_resource(k)
            wrong += int(held != truth["res"].get(k))
            lag = newest_t - truth["res_t"].get(held, 0.0)  # true seconds by which the held report trails the newest
            lags.append(lag)
            old += int(lag > 2.0)  # the legacy drift guard's own tolerance
    out["res_stale"] = wrong / tot if tot else None
    out["res_stale2"] = old / tot if tot else None
    out["res_lag_s"] = sum(lags) / len(lags) if lags else None

    out["bytes"] = sum(replicas[n].state_bytes() for n in nodes) / nrep
    out["delivered"] = delivered
    return out
