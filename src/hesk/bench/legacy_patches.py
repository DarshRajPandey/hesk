"""Surgical patches to the *legacy* ledger, used to attribute system-level failures to causes.

Each patch removes exactly one verified defect from the unmodified code path:

  resolver  ownership conflicts are resolved with a total order (exact lexicographic), not the
            epsilon cascade                                                     (defect F1)
  window    the 5 s wall-clock "potentially concurrent" test is disabled, so ordering falls back
            to Lamport clocks                                                   (defect F2)
  clock     received entries keep the *origin* Lamport clock instead of the receiver's
                                                                                (defect F3)

Patch names are appended to an implementation name: ``legacy/always/direct+resolver+clock``.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from typing import Iterator, Sequence
from unittest import mock

import hesk.ledger.ledger as ledger_mod
import hesk.ledger.reconciliation as recon_mod
from hesk.ledger.model import Conflict, Resolution, SideEffect, SideEffectType

PATCH_NAMES = ("resolver", "window", "clock")


def _total_order_resolution(conflict: Conflict) -> Resolution:
    local, remote = conflict.local_entry, conflict.remote_entry
    info = recon_mod._extract_task_info
    la, lp, lq = info(local.value)
    ra, rp, rq = info(remote.value)
    key = lambda a, p, q, wall: (-p, -q, wall, str(a))
    w, l = (local, remote) if key(la, lp, lq, local.wall_time) <= key(ra, rp, rq, remote.wall_time) else (remote, local)
    wa, la_ = info(w.value)[0], info(l.value)[0]
    return Resolution("EXCLUSIVE_OWNERSHIP_TOTAL_ORDER", w.value, w.source_node, "total order",
                      [SideEffect(SideEffectType.RELEASE_EXECUTOR, la_, conflict.key),
                       SideEffect(SideEffectType.NOTIFY_WINNER, wa, conflict.key)])


@contextmanager
def apply(names: Sequence[str]) -> Iterator[None]:
    unknown = set(names) - set(PATCH_NAMES)
    if unknown:
        raise KeyError(unknown)
    with ExitStack() as st:
        if "resolver" in names:
            st.enter_context(mock.patch.object(recon_mod, "resolve_exclusive_ownership", _total_order_resolution))
        if "window" in names:
            st.enter_context(mock.patch.object(ledger_mod, "is_potentially_concurrent", lambda *a, **k: False))
        if "clock" in names:
            orig = ledger_mod.LocalStateLedger.write_received

            def write_received(self, key, value, semantic_type, source_node, source_clock, *rest, **kw):
                entry, changed = orig(self, key, value, semantic_type, source_node, source_clock, *rest, **kw)
                if changed:
                    entry.lamport_clock = source_clock
                return entry, changed

            st.enter_context(mock.patch.object(ledger_mod.LocalStateLedger, "write_received", write_received))
        yield
