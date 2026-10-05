"""Unreliable broadcast radio model.

One transmission reaches every other live node in the sender's partition
component; each receiver independently loses it. Loss can be i.i.d.
(Bernoulli) or bursty (Gilbert-Elliott two-state chain per directed link,
which is how real jamming and fading behave: losses come in runs).
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Tuple

from hesk_sim.engine import EventLoop


@dataclass
class Message:
    kind: str
    src: str
    payload: dict
    size: int = 64  # bytes, rough wire size for bandwidth accounting
    dst: Optional[str] = None  # None = broadcast


@dataclass
class NetStats:
    tx: int = 0            # transmissions (a broadcast counts once)
    tx_bytes: int = 0
    deliveries: int = 0
    drops: int = 0
    by_kind: Dict[str, int] = field(default_factory=dict)


class Network:
    def __init__(self, loop: EventLoop, rng: random.Random, *, loss: float = 0.0,
                 burst_len: float = 1.0, latency: float = 0.02, jitter: float = 0.01,
                 jam: Optional[Tuple[float, float, float]] = None):
        self.loop = loop
        self.rng = rng
        self.loss = loss
        self.burst_len = max(1.0, burst_len)
        self.latency = latency
        self.jitter = jitter
        self.jam = jam  # (t_start, t_end, loss during window)
        self.group: Dict[str, int] = {}
        self.alive: Dict[str, bool] = {}
        self.handlers: Dict[str, Callable[[Message], None]] = {}
        self._bad: Dict[Tuple[str, str], bool] = {}  # Gilbert-Elliott link state
        self.stats = NetStats()

    def register(self, node_id: str, handler: Callable[[Message], None]) -> None:
        self.handlers[node_id] = handler
        self.alive[node_id] = True
        self.group[node_id] = 0

    def set_partition(self, groups: List[List[str]]) -> None:
        for gi, members in enumerate(groups):
            for n in members:
                self.group[n] = gi

    def heal(self) -> None:
        for n in self.group:
            self.group[n] = 0

    def current_loss(self) -> float:
        if self.jam and self.jam[0] <= self.loop.now < self.jam[1]:
            return self.jam[2]
        return self.loss

    def _lost(self, src: str, dst: str, p: float) -> bool:
        if p <= 0.0:
            return False
        if p >= 1.0:
            return True
        if self.burst_len <= 1.0:
            return self.rng.random() < p
        # Gilbert-Elliott: stationary P(bad) = p, mean bad-run length = burst_len.
        key = (src, dst)
        bad = self._bad.get(key, self.rng.random() < p)
        p_bg = 1.0 / self.burst_len
        p_gb = p_bg * p / (1.0 - p)
        if bad:
            bad = self.rng.random() >= p_bg
        else:
            bad = self.rng.random() < p_gb
        self._bad[key] = bad
        return bad

    def send(self, msg: Message) -> None:
        if not self.alive.get(msg.src, False):
            return
        st = self.stats
        st.tx += 1
        st.tx_bytes += msg.size
        st.by_kind[msg.kind] = st.by_kind.get(msg.kind, 0) + 1
        g = self.group[msg.src]
        p = self.current_loss()
        targets = [msg.dst] if msg.dst is not None else [n for n in self.handlers if n != msg.src]
        for dst in targets:
            if not self.alive.get(dst, False) or self.group.get(dst) != g:
                continue
            if self._lost(msg.src, dst, p):
                st.drops += 1
                continue
            delay = self.latency + self.rng.expovariate(1.0 / self.jitter) if self.jitter > 0 else self.latency
            handler = self.handlers[dst]
            self.loop.after(delay, lambda h=handler, m=msg, d=dst: self._deliver(h, m, d))

    def _deliver(self, handler: Callable[[Message], None], msg: Message, dst: str) -> None:
        # A node killed while the packet was in flight never receives it.
        if self.alive.get(dst, False):
            self.stats.deliveries += 1
            handler(msg)
