"""Deterministic discrete-event simulation core.

Everything stochastic in a run draws from named sub-streams of one master
seed, so a run is a pure function of (scenario config, algorithm config,
seed). Two runs with the same inputs produce byte-identical metrics on any
machine with the same Python/NumPy versions.
"""
from __future__ import annotations

import hashlib
import heapq
import random
from typing import Any, Callable, List, Tuple


def derive_seed(*parts: Any) -> int:
    """Stable 63-bit seed from arbitrary parts (independent of PYTHONHASHSEED)."""
    h = hashlib.sha256("|".join(str(p) for p in parts).encode()).digest()
    return int.from_bytes(h[:8], "big") & ((1 << 63) - 1)


class RngStreams:
    """Independent RNG streams so that e.g. adding a fault does not reshuffle
    the scenario layout (common random numbers across experimental arms)."""

    def __init__(self, master_seed: int):
        self.master_seed = master_seed
        self._streams: dict[str, random.Random] = {}

    def get(self, name: str) -> random.Random:
        if name not in self._streams:
            self._streams[name] = random.Random(derive_seed(self.master_seed, name))
        return self._streams[name]


class EventLoop:
    def __init__(self) -> None:
        self.now = 0.0
        self._q: List[Tuple[float, int, Callable[[], None]]] = []
        self._seq = 0

    def at(self, t: float, fn: Callable[[], None]) -> None:
        self._seq += 1
        heapq.heappush(self._q, (t, self._seq, fn))

    def after(self, dt: float, fn: Callable[[], None]) -> None:
        self.at(self.now + dt, fn)

    def run_until(self, t_end: float) -> None:
        q = self._q
        while q and q[0][0] <= t_end:
            t, _, fn = heapq.heappop(q)
            self.now = t
            fn()
        self.now = t_end
