"""Injectable wall clock.

The ledger reads wall time through :func:`now`. Production code uses the system
clock; the simulator installs a virtual clock so that every experiment is a pure
function of its seed.
"""
import time
from contextlib import contextmanager
from typing import Callable, Iterator

_clock: Callable[[], float] = time.time


def now() -> float:
    return _clock()


@contextmanager
def use_clock(fn: Callable[[], float]) -> Iterator[None]:
    """Temporarily replace the wall clock (restores the previous one on exit)."""
    global _clock
    prev, _clock = _clock, fn
    try:
        yield
    finally:
        _clock = prev
