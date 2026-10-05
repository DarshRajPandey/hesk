"""Semilattice-law property tests for the HESK-L cells.

States are produced by *reachable* histories (random local writes interleaved with
random pairwise joins on three replicas), because dotted-version-vector semantics
only hold on states a real system can reach.
"""
import itertools

import pytest
from hypothesis import given, settings, strategies as st

from hesk.ledger.lattice import GCounter, LWW, MVRegister, ObsSet, resolve_versions

NODES = ["A", "B", "C"]

op = st.one_of(
    st.tuples(st.just("write"), st.integers(0, 2), st.floats(0, 1), st.floats(0, 1), st.floats(0, 100)),
    st.tuples(st.just("sync"), st.integers(0, 2), st.integers(0, 2)),
)
histories = st.lists(op, max_size=40)


def run(history, make, write):
    reps = [make() for _ in NODES]
    for o in history:
        if o[0] == "write":
            write(reps[o[1]], NODES[o[1]], o)
        else:
            reps[o[1]] = reps[o[1]].join(reps[o[2]])
    return reps


def laws(reps):
    a, b, c = reps
    assert a.join(b).canonical() == b.join(a).canonical()
    assert a.join(b).join(c).canonical() == a.join(b.join(c)).canonical()
    assert a.join(a).canonical() == a.canonical()


def _mv_write(r, n, o):
    r.write(n, f"{n}{o[1]}", o[2], o[3], o[4])


@settings(max_examples=300, deadline=None)
@given(histories)
def test_mvregister_is_a_semilattice(h):
    laws(run(h, MVRegister, _mv_write))


@settings(max_examples=300, deadline=None)
@given(histories)
def test_gcounter_is_a_semilattice(h):
    laws(run(h, GCounter, lambda r, n, o: r.increment(n)))


@settings(max_examples=300, deadline=None)
@given(histories)
def test_obsset_is_a_semilattice(h):
    laws(run(h, ObsSet, lambda r, n, o: r.observe(n, o[2], o[4])))


@settings(max_examples=300, deadline=None)
@given(histories)
def test_lww_is_a_semilattice(h):
    laws(run(h, LWW, lambda r, n, o: r.set(n, o[2], o[4])))


@settings(max_examples=200, deadline=None)
@given(histories)
def test_mvregister_replicas_that_exchange_everything_agree(h):
    a, b, c = run(h, MVRegister, _mv_write)
    merged = a.join(b).join(c)
    for r in (a, b, c):
        for policy in ("exact", "bucketed", "eps"):
            assert r.join(merged).resolve(policy) == merged.resolve(policy)


def test_causal_handoff_supersedes_even_within_milliseconds():
    a, b = MVRegister(), MVRegister()
    a.write("A", "A", 0.9, 0.9, 10.0)
    b = b.join(a)
    b.write("B", "B", 0.1, 0.1, 10.001)  # causally after A's claim, much lower progress
    merged = a.join(b)
    assert [v.assignee for v in merged.versions.values()] == ["B"]


def test_counter_keeps_concurrent_increments():
    a, b = GCounter(), GCounter()
    a.increment("A"), b.increment("B")
    assert a.join(b).value() == 2


def test_obsset_is_idempotent_under_redelivery():
    a, b = ObsSet(), ObsSet()
    a.observe("A", 1, 0.0)
    for _ in range(3):
        b = b.join(a)
    assert len(b.values()) == 1


def test_legacy_epsilon_cascade_is_not_a_total_order():
    """A beats B, B beats C, C beats A: the pairwise rule has a cycle."""
    from hesk.ledger.lattice import Version, _legacy_pair_winner

    A = Version(("A", 1), "A", 0.00, 0.90, 10.0)
    B = Version(("B", 1), "B", 0.04, 0.50, 11.0)
    C = Version(("C", 1), "C", 0.08, 0.10, 12.0)
    assert _legacy_pair_winner(A, B).assignee == "A"
    assert _legacy_pair_winner(B, C).assignee == "B"
    assert _legacy_pair_winner(A, C).assignee == "C"


@pytest.mark.parametrize("policy", ["exact", "bucketed"])
def test_total_order_policies_are_order_independent(policy):
    from hesk.ledger.lattice import Version

    vs = [Version(("A", 1), "A", 0.00, 0.90, 10.0), Version(("B", 1), "B", 0.04, 0.50, 11.0),
          Version(("C", 1), "C", 0.08, 0.10, 12.0)]
    winners = {resolve_versions(list(p), policy).assignee for p in itertools.permutations(vs)}
    assert len(winners) == 1
