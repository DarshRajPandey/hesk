"""E9: is the legacy ownership comparator a valid merge function? (pure computation, no network)

A merge used by a convergent replicated store must be order-independent. We draw sets of
concurrent claims and fold them pairwise in every order, counting how often the *winner*
depends on the order. A total-order policy can never be order-dependent (we check that
empirically as a control); the legacy epsilon-cascade can.
"""
from __future__ import annotations

import itertools
import random
from typing import Dict, List

from hesk.ledger.lattice import Version, _legacy_pair_winner, resolve_versions


def draw(rng: random.Random, k: int, spread: float) -> List[Version]:
    return [
        Version((f"n{i}", 1), f"n{i}", min(1.0, max(0.0, rng.gauss(0.5, spread))), rng.uniform(0.2, 1.0), rng.uniform(0.0, 5.0))
        for i in range(k)
    ]


def fold(vs: List[Version]) -> str:
    cur = vs[0]
    for nxt in vs[1:]:
        cur = _legacy_pair_winner(cur, nxt)
    return cur.assignee


def trial(k: int, spread: float, seed: int, max_orders: int = 120) -> Dict[str, float]:
    rng = random.Random(f"alg:{k}:{spread}:{seed}")
    vs = draw(rng, k, spread)
    perms = list(itertools.permutations(vs))
    if len(perms) > max_orders:
        perms = rng.sample(perms, max_orders)
    legacy = {fold(list(p)) for p in perms}
    exact = {resolve_versions(list(p), "exact").assignee for p in perms}
    bucketed = {resolve_versions(list(p), "bucketed").assignee for p in perms}
    cycle = 0
    if k >= 3:
        for a, b, c in itertools.combinations(vs, 3):
            w = (_legacy_pair_winner(a, b).assignee, _legacy_pair_winner(b, c).assignee, _legacy_pair_winner(a, c).assignee)
            cycle += int(len(set(w)) == 3)  # a>b, b>c, c>a  <=>  the three pairwise winners are all different
    best = max(v.progress for v in vs)
    win = lambda name: next(v for v in vs if v.assignee == name).progress
    first = fold(vs)
    return {
        "legacy_order_dependent": float(len(legacy) > 1),
        "legacy_n_winners": float(len(legacy)),
        "exact_order_dependent": float(len(exact) > 1),
        "bucketed_order_dependent": float(len(bucketed) > 1),
        "has_cycle": float(cycle > 0),
        "regret_legacy_first_order": best - win(first),
        "regret_exact": best - resolve_versions(vs, "exact").progress,
        "regret_bucketed": best - resolve_versions(vs, "bucketed").progress,
    }
