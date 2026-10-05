"""Replica adapters: one workload interface over the legacy ledger and HESK-L."""
from __future__ import annotations

import copy
import pickle
from dataclasses import dataclass, replace
from typing import Any, Dict, FrozenSet, Optional, Tuple

from hesk.ledger import lattice as lat
from hesk.ledger.ledger import LocalStateLedger, accept_resource_update, local_wall_time
from hesk.ledger.model import (
    LedgerEntry, Observation, ObservationType, Provenance, StateExchangeMessage, StateSemanticType,
)
from hesk.ledger.reconciliation import reconcile_full_ledger

OwnerView = Optional[Tuple[str, float, float]]  # (assignee, progress, match_quality)


class Replica:
    """What a node exposes to the workload. Reads return *observable* state only."""

    node_id: str

    def claim(self, key: str, assignee: str, progress: float, quality: float) -> None: raise NotImplementedError
    def increment(self, key: str) -> None: raise NotImplementedError
    def observe(self, key: str, token: int) -> None: raise NotImplementedError
    def report(self, key: str, token: int) -> None: raise NotImplementedError
    def snapshot(self) -> Any: raise NotImplementedError
    def clone_payload(self, payload: Any) -> Any: return copy.deepcopy(payload)  # what the wire does to a message
    def receive(self, payload: Any, sender: str, reconnected: bool) -> None: raise NotImplementedError
    def read_owner(self, key: str) -> OwnerView: raise NotImplementedError
    def read_counter(self, key: str) -> int: raise NotImplementedError
    def read_obs(self, key: str) -> Tuple[FrozenSet[int], int]: raise NotImplementedError  # (distinct tokens, entries held)
    def read_resource(self, key: str) -> Optional[int]: raise NotImplementedError
    def state_bytes(self) -> int: raise NotImplementedError
    def units(self, payload: Any) -> int: return 0  # cheap payload-size proxy used by the simulator's resource guard


# ─── The system under test, unmodified ────────────────────────────────────────

class LegacyReplica(Replica):
    """Wraps ``LocalStateLedger`` exactly as shipped.

    mode="gossip"     every message goes through ``process_message``.
    mode="reconcile"  the first message after a partition goes through
                      ``reconcile_full_ledger`` (the documented reconnection path);
                      everything else through ``process_message``.
    mode="always"     every message goes through ``reconcile_full_ledger`` (continuous anti-entropy).
    relay=True        a node gossips every entry it holds (multi-hop relay).
    relay=False       a node gossips only entries it authored (direct-only); this removes the
                      second-hop interactions and is the most favourable reading of the protocol.
    """

    def __init__(self, node_id: str, mode: str = "reconcile", relay: bool = True):
        assert mode in ("gossip", "reconcile", "always")
        self.node_id, self.mode, self.relay = node_id, mode, relay
        self.ledger = LocalStateLedger(node_id)

    def claim(self, key, assignee, progress, quality):
        self.ledger.write_local(key, {"assignee": assignee, "progress": progress, "match_quality": quality},
                                StateSemanticType.EXCLUSIVE_OWNERSHIP)

    def increment(self, key):
        cur, _ = self.ledger.read(key)
        self.ledger.write_local(key, (cur or 0) + 1, StateSemanticType.COUNTER)

    def observe(self, key, token):
        self.ledger.write_local(key, token, StateSemanticType.OBSERVATIONAL)

    def report(self, key, token):
        self.ledger.write_local(key, token, StateSemanticType.RESOURCE)

    def snapshot(self):
        entries = [e for e in self.ledger.entries.values() if self.relay or e.source_node == self.node_id]
        return StateExchangeMessage(self.node_id, self.ledger.lamport_clock, dict(self.ledger.version_vector),
                                    copy.deepcopy(entries))

    def receive(self, payload, sender, reconnected):
        if self.mode == "always" or (reconnected and self.mode == "reconcile"):
            reconcile_full_ledger(self.ledger, sender, {e.key: e for e in payload.entries})
        else:
            self.ledger.process_message(payload)

    def read_owner(self, key):
        e = self.ledger.entries.get(key)
        if e is None or not isinstance(e.value, dict):
            return None
        return (e.value["assignee"], e.value["progress"], e.value["match_quality"])

    def read_counter(self, key):
        e = self.ledger.entries.get(key)
        return int(e.value) if e is not None else 0

    def read_obs(self, key):
        e = self.ledger.entries.get(key)
        if e is None:
            return frozenset(), 0
        leaves = []
        _flatten(e.value, leaves)
        return frozenset(leaves), len(leaves)

    def read_resource(self, key):
        e = self.ledger.entries.get(key)
        return None if e is None else e.value

    def state_bytes(self):
        return len(pickle.dumps(list(self.ledger.entries.values())))

    def units(self, payload):
        n = 0
        for e in payload.entries:
            if e.semantic_type == StateSemanticType.OBSERVATIONAL:
                leaves: list = []
                _flatten(e.value, leaves)
                n += len(leaves)
        return n


def _flatten(v: Any, out: list) -> None:
    """Legacy observation values can nest (a relayed list gets wrapped in an Observation)."""
    if isinstance(v, Observation):
        _flatten(v.value, out)
    elif isinstance(v, list):
        for x in v:
            _flatten(x, out)
    else:
        out.append(v)


# ─── HESK-L with ablation switches ────────────────────────────────────────────

@dataclass(frozen=True)
class LatticeConfig:
    """Each field's non-default value re-introduces the corresponding legacy behaviour."""
    name: str = "hesk-l"
    ownership: str = "mv"        # mv (causal multi-value register) | lww (last wall-clock write wins)
    resolver: str = "bucketed"   # bucketed | exact | eps          (ownership read policy)
    counter: str = "gcounter"    # gcounter | max                   (max = legacy lost-update)
    observations: str = "dedup"  # dedup | append                   (append = legacy non-idempotent)
    resource: str = "lww"        # lww | drift_guard                (drift_guard = legacy +/-2s window)


FULL = LatticeConfig()
ABLATIONS: Tuple[LatticeConfig, ...] = (
    FULL,
    replace(FULL, name="hesk-l/exact", resolver="exact"),
    replace(FULL, name="hesk-l/eps-resolver", resolver="eps"),
    replace(FULL, name="hesk-l/-gcounter", counter="max"),
    replace(FULL, name="hesk-l/-dedup", observations="append"),
    replace(FULL, name="hesk-l/-lww", resource="drift_guard"),
    replace(FULL, name="hesk-l/-all", resolver="eps", counter="max", observations="append", resource="drift_guard"),
)

# Conventional AP baseline (Apache Cassandra / DynamoDB global tables style): every CRDT fix HESK-L
# has, except ownership, which is a last-writer-wins register on wall-clock time.
LWW_GOSSIP = replace(FULL, name="baseline/lww-gossip", ownership="lww")


class LatticeReplica(Replica):
    def __init__(self, node_id: str, cfg: LatticeConfig = FULL):
        self.node_id, self.cfg = node_id, cfg
        self.cells: Dict[str, Any] = {}

    # writes
    def claim(self, key, assignee, progress, quality):
        if self.cfg.ownership == "lww":
            self.cells.setdefault(key, lat.LWW()).set(self.node_id, (assignee, progress, quality), local_wall_time())
        else:
            self.cells.setdefault(key, lat.MVRegister()).write(self.node_id, assignee, progress, quality, local_wall_time())

    def increment(self, key):
        if self.cfg.counter == "gcounter":
            self.cells.setdefault(key, lat.GCounter()).increment(self.node_id)
        else:  # legacy semantics: read, add one, publish the absolute value, merge with max
            self.cells[key] = self.cells.get(key, 0) + 1

    def observe(self, key, token):
        now = local_wall_time()
        if self.cfg.observations == "dedup":
            self.cells.setdefault(key, lat.ObsSet()).observe(self.node_id, token, now)
        else:
            self.cells.setdefault(key, []).append((now, token))
            self._trim_list(key)

    def report(self, key, token):
        now = local_wall_time()
        if self.cfg.resource == "lww":
            self.cells.setdefault(key, lat.LWW()).set(self.node_id, token, now)
        else:
            self.cells[key] = _GuardedValue(token, now, self.node_id)

    def _trim_list(self, key):
        lst = self.cells[key]
        if len(lst) > lat.OBS_TOP_K:
            self.cells[key] = sorted(lst, key=lambda x: x[0], reverse=True)[: lat.OBS_TOP_K]

    # replication
    def snapshot(self):
        return self.clone_payload(self.cells)

    def clone_payload(self, payload):
        return {k: (c.copy() if hasattr(c, "copy") else copy.deepcopy(c)) for k, c in payload.items()}

    def receive(self, payload, sender, reconnected):
        for key, remote in payload.items():
            local = self.cells.get(key)
            if local is None:
                self.cells[key] = remote  # payload was already cloned at delivery
            elif isinstance(remote, list):            # legacy-style append on receive
                self.cells[key] = local + remote
                self._trim_list(key)
            elif isinstance(remote, int):             # legacy-style max
                self.cells[key] = max(local, remote)
            elif isinstance(remote, _GuardedValue):   # legacy-style drift guard
                local.accept(remote)
            else:
                self.cells[key] = local.join(remote)

    # reads
    def read_owner(self, key):
        c = self.cells.get(key)
        if isinstance(c, lat.LWW):
            return c.value
        v = c.resolve(self.cfg.resolver) if c is not None else None
        return None if v is None else (v.assignee, v.progress, v.quality)

    def read_counter(self, key):
        c = self.cells.get(key)
        if c is None:
            return 0
        return c.value() if isinstance(c, lat.GCounter) else c

    def read_obs(self, key):
        c = self.cells.get(key)
        if c is None:
            return frozenset(), 0
        vals = list(c.values()) if isinstance(c, lat.ObsSet) else [t for _, t in c]
        return frozenset(vals), len(vals)

    def read_resource(self, key):
        c = self.cells.get(key)
        return None if c is None else c.value

    def state_bytes(self):
        return len(pickle.dumps(self.cells))


class _GuardedValue:
    """Resource cell using the legacy ``accept_resource_update`` rule verbatim."""

    __slots__ = ("value", "wall_time", "node")

    def __init__(self, value, wall_time, node):
        self.value, self.wall_time, self.node = value, wall_time, node

    def accept(self, remote: "_GuardedValue") -> None:
        local_entry = _as_entry(self)
        prov = Provenance(remote.node, ObservationType.DIRECT, 0)
        if accept_resource_update(local_entry, remote.wall_time, 1.0, prov):
            self.value, self.node = remote.value, remote.node
            self.wall_time = max(self.wall_time, remote.wall_time)  # as in write_received


def _as_entry(g: _GuardedValue) -> LedgerEntry:
    return LedgerEntry("k", g.value, StateSemanticType.RESOURCE, g.node, 0, g.wall_time, 1.0,
                       Provenance(g.node, ObservationType.DIRECT, 0))


# ─── Conventional CP baseline: an idealised Raft / Paxos replicated state machine ──────────

class QuorumReplica(Replica):
    """A replicated log behind a quorum (the etcd / Consul / CockroachDB model), idealised.

    * A write commits only if the writer can reach a majority of the configured cluster
      (``World.commit_ok``); leader election and failure detection are free and instant.
    * Ownership claims are compare-and-set on the owner the node last saw, so a task can never
      have two committed owners. A claim that cannot commit is refused: the task stays orphaned.
    * Counter increments and observations that cannot commit are queued and retried (nothing is
      lost unless the node dies first); stale telemetry (resource reports) is dropped.
    * A node's reads come from its last synchronisation with the majority (follower reads).
    """

    def __init__(self, node_id: str):
        self.node_id = node_id
        self.view: Dict[str, Any] = {}
        self.queue: list = []
        self.world = None

    def attach(self, world) -> None:
        self.world = world

    def _sync(self) -> None:
        self.view = copy.deepcopy(self.world.log)

    def _apply(self, op) -> None:
        kind, key, val = op
        log = self.world.log
        if kind == "inc":
            log[key] = log.get(key, 0) + 1
        elif kind == "obs":
            lst = log.setdefault(key, [])
            if val not in lst:
                lst.append(val)
                lst.sort()
                del lst[:-lat.OBS_TOP_K]

    def claim(self, key, assignee, progress, quality):
        if not self.world.commit_ok(self.node_id):
            return False
        expected = self.view.get(key)
        if self.world.log.get(key) != expected:  # someone else committed first: CAS fails
            self._sync()
            return False
        self.world.log[key] = (assignee, progress, quality)
        self._sync()
        return True

    def _write(self, op) -> None:
        if self.world.commit_ok(self.node_id):
            self._apply(op)
            self._sync()
        else:
            self.queue.append(op)

    def increment(self, key):
        self._write(("inc", key, None))

    def observe(self, key, token):
        self._write(("obs", key, token))

    def report(self, key, token):
        if self.world.commit_ok(self.node_id):
            self.world.log[key] = token
            self._sync()

    def snapshot(self):  # called on every gossip tick: heartbeat to the leader
        if self.world.commit_ok(self.node_id, attempts=1):
            for op in self.queue:
                self._apply(op)
            self.queue = []
            self._sync()
        return None

    def clone_payload(self, payload):
        return None

    def receive(self, payload, sender, reconnected):
        return None

    def read_owner(self, key):
        return self.view.get(key)

    def read_counter(self, key):
        return self.view.get(key, 0)

    def read_obs(self, key):
        lst = self.view.get(key, [])
        return frozenset(lst), len(lst)

    def read_resource(self, key):
        return self.view.get(key)

    def state_bytes(self):
        return len(pickle.dumps(self.view))
