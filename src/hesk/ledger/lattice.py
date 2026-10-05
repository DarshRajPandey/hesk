"""HESK-L: a join-semilattice reference implementation of the HESK ledger.

The legacy ledger (``hesk.ledger.ledger`` / ``reconciliation``) merges state with
rules that are *not* joins: ``max`` for counters, append-on-receive for
observations, a 5-second wall-clock window for ownership concurrency, and a
pairwise epsilon-cascade comparator for ownership conflicts. A state-based
replicated store only converges (strong eventual consistency) when its merge is
commutative, associative and idempotent (Shapiro et al., 2011), so each of these
rules has a counterpart here that is a genuine lattice join:

====================  =====================================  ======================
state                 legacy merge                           HESK-L cell
====================  =====================================  ======================
EXCLUSIVE_OWNERSHIP   window heuristic + eps-cascade         ``MVRegister`` (DVV set)
COUNTER               ``max``                                ``GCounter``
OBSERVATIONAL         append on receive                      ``ObsSet`` (bounded top-k)
RESOURCE              +/-DRIFT_MAX window, first-writer      ``LWW`` on (wall, node)
====================  =====================================  ======================

Every cell exposes ``join`` (pure, returns a new cell) and the property tests in
``tests/unit/test_lattice_laws.py`` check the three semilattice laws.

Ownership conflicts are *not* resolved by rewriting state. The register keeps all
causally-concurrent versions and a deterministic *read-time* policy picks the
visible owner. Because the policy is a pure function of the version set, every
replica that has seen the same versions shows the same owner, regardless of merge
order.
"""
from __future__ import annotations

import copy
import math
from dataclasses import dataclass
from typing import Callable, Dict, Iterable, List, Optional, Tuple

Dot = Tuple[str, int]  # (node_id, per-key sequence number)

OBS_TOP_K = 5
RESOLUTION_EPS = 0.05  # progress / quality granularity used by the ``bucketed`` policy


# ─── Ownership: multi-value register over dotted version vectors ──────────────

@dataclass(frozen=True)
class Version:
    dot: Dot
    assignee: str
    progress: float
    quality: float
    wall_time: float


def _covered(dot: Dot, vv: Dict[str, int]) -> bool:
    return vv.get(dot[0], 0) >= dot[1]


class MVRegister:
    """Concurrent versions of one ownership key plus the version vector seen so far."""

    __slots__ = ("versions", "seen")

    def __init__(self, versions: Optional[Dict[Dot, Version]] = None, seen: Optional[Dict[str, int]] = None):
        self.versions: Dict[Dot, Version] = dict(versions or {})
        self.seen: Dict[str, int] = dict(seen or {})

    def write(self, node: str, assignee: str, progress: float, quality: float, wall_time: float) -> Version:
        """A local write supersedes every version this replica has seen."""
        seq = self.seen.get(node, 0) + 1
        v = Version((node, seq), assignee, progress, quality, wall_time)
        self.versions = {v.dot: v}
        self.seen[node] = seq
        return v

    def join(self, other: "MVRegister") -> "MVRegister":
        keep: Dict[Dot, Version] = {}
        for d, v in self.versions.items():
            if d in other.versions or not _covered(d, other.seen):
                keep[d] = v
        for d, v in other.versions.items():
            if d in self.versions or not _covered(d, self.seen):
                keep[d] = v
        seen = dict(self.seen)
        for n, s in other.seen.items():
            if s > seen.get(n, 0):
                seen[n] = s
        return MVRegister(keep, seen)

    def copy(self) -> "MVRegister":
        return MVRegister(self.versions, self.seen)  # Version is frozen; dicts are copied by __init__

    def canonical(self) -> Tuple:
        return (tuple(sorted(self.versions.values(), key=lambda v: v.dot)), tuple(sorted(self.seen.items())))

    def resolve(self, policy: str) -> Optional[Version]:
        return resolve_versions(list(self.versions.values()), policy)


def _legacy_pair_winner(a: Version, b: Version) -> Version:
    """Winner of the legacy epsilon-cascade comparator (``resolve_exclusive_ownership``)."""
    from hesk.ledger.model import (  # local import: keeps this module dependency-light
        Conflict, LedgerEntry, ObservationType, Provenance, StateSemanticType,
    )
    from hesk.ledger.reconciliation import resolve_exclusive_ownership

    def entry(v: Version) -> LedgerEntry:
        return LedgerEntry(
            key="k", value={"assignee": v.assignee, "progress": v.progress, "match_quality": v.quality},
            semantic_type=StateSemanticType.EXCLUSIVE_OWNERSHIP, source_node=v.dot[0], lamport_clock=v.dot[1],
            wall_time=v.wall_time, confidence=1.0,
            provenance=Provenance(v.dot[0], ObservationType.DIRECT, v.dot[1]),
        )

    res = resolve_exclusive_ownership(Conflict("k", entry(a), entry(b), StateSemanticType.EXCLUSIVE_OWNERSHIP))
    return a if res.winning_value["assignee"] == a.assignee else b


def resolve_versions(versions: List[Version], policy: str) -> Optional[Version]:
    """Deterministic owner choice from a *set* of concurrent versions.

    ``exact``     lexicographic (progress, quality, earlier wall time, node id); a total order.
    ``bucketed``  same, but progress/quality are floored to RESOLUTION_EPS buckets, which keeps
                  the legacy intent "differences under 5% are ties" and is still a total order.
    ``eps``       the legacy pairwise epsilon-cascade folded in node-id order (not a total order;
                  deterministic here only because the fold order is canonicalised).
    """
    if not versions:
        return None
    if policy == "exact":
        return min(versions, key=lambda v: (-v.progress, -v.quality, v.wall_time, v.dot[0], v.dot[1]))
    if policy == "bucketed":
        b = lambda x: math.floor(x / RESOLUTION_EPS + 1e-9)
        return min(versions, key=lambda v: (-b(v.progress), -b(v.quality), v.wall_time, v.dot[0], v.dot[1]))
    if policy == "eps":
        ordered = sorted(versions, key=lambda v: v.dot)
        cur = ordered[0]
        for nxt in ordered[1:]:
            cur = _legacy_pair_winner(cur, nxt)
        return cur
    raise ValueError(f"unknown resolution policy {policy!r}")


# ─── Counter: grow-only counter ───────────────────────────────────────────────

class GCounter:
    __slots__ = ("counts",)

    def __init__(self, counts: Optional[Dict[str, int]] = None):
        self.counts: Dict[str, int] = dict(counts or {})

    def increment(self, node: str, delta: int = 1) -> None:
        self.counts[node] = self.counts.get(node, 0) + delta

    def value(self) -> int:
        return sum(self.counts.values())

    def join(self, other: "GCounter") -> "GCounter":
        out = dict(self.counts)
        for n, c in other.counts.items():
            if c > out.get(n, 0):
                out[n] = c
        return GCounter(out)

    def copy(self) -> "GCounter":
        return GCounter(self.counts)

    def canonical(self) -> Tuple:
        return tuple(sorted(self.counts.items()))


# ─── Observations: deduplicated bounded set ───────────────────────────────────

ObsId = Tuple[str, int]


class ObsSet:
    """Observations keyed by (origin, per-origin sequence); keeps the newest ``k``.

    "Newest" is the total order (stamp, origin, seq), where ``stamp`` is the observer's
    wall time, so truncating a union is deterministic and merge order cannot matter.
    """

    __slots__ = ("items", "next_seq", "k")

    def __init__(self, items: Optional[Dict[ObsId, Tuple[float, object]]] = None,
                 next_seq: Optional[Dict[str, int]] = None, k: int = OBS_TOP_K):
        self.items: Dict[ObsId, Tuple[float, object]] = dict(items or {})
        self.next_seq: Dict[str, int] = dict(next_seq or {})
        self.k = k

    def observe(self, node: str, value: object, stamp: float) -> ObsId:
        seq = self.next_seq.get(node, 0) + 1
        self.next_seq[node] = seq
        oid = (node, seq)
        self.items[oid] = (stamp, value)
        self._truncate()
        return oid

    def _truncate(self) -> None:
        if len(self.items) > self.k:
            top = sorted(self.items, key=lambda i: (self.items[i][0], i[0], i[1]), reverse=True)[: self.k]
            self.items = {i: self.items[i] for i in top}

    def join(self, other: "ObsSet") -> "ObsSet":
        out = ObsSet({**self.items, **other.items}, dict(self.next_seq), self.k)
        for n, s in other.next_seq.items():
            if s > out.next_seq.get(n, 0):
                out.next_seq[n] = s
        out._truncate()
        return out

    def copy(self) -> "ObsSet":
        return ObsSet(self.items, self.next_seq, self.k)

    def values(self) -> Tuple[object, ...]:
        return tuple(v for _, v in (self.items[i] for i in sorted(self.items)))

    def canonical(self) -> Tuple:
        return (tuple(sorted(self.items.items())), tuple(sorted(self.next_seq.items())))


# ─── Resource: last-writer-wins on a total order ──────────────────────────────

class LWW:
    __slots__ = ("value", "wall_time", "node")

    def __init__(self, value: object = None, wall_time: float = -math.inf, node: str = ""):
        self.value, self.wall_time, self.node = value, wall_time, node

    def set(self, node: str, value: object, wall_time: float) -> None:
        if (wall_time, node) > (self.wall_time, self.node):
            self.value, self.wall_time, self.node = value, wall_time, node

    def join(self, other: "LWW") -> "LWW":
        return copy.copy(self) if (self.wall_time, self.node) >= (other.wall_time, other.node) else copy.copy(other)

    def copy(self) -> "LWW":
        return copy.copy(self)

    def canonical(self) -> Tuple:
        return (self.value, self.wall_time, self.node)
