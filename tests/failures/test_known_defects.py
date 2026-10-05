"""Characterisation of verified defects in the legacy ledger (docs/research/FINDINGS.md, F1-F9).

Each test states the *correct* behaviour and is ``xfail(strict=True)``: it fails today, and the
suite will go red the day a defect is fixed so this file (and the findings) must be updated.
The matching HESK-L behaviour is asserted in tests/unit/test_lattice_laws.py.
"""
from unittest import mock

import pytest

import hesk.ledger.ledger as L
from hesk.ledger.ledger import LocalStateLedger
from hesk.ledger.model import (
    Conflict, LedgerEntry, ObservationType, Provenance, StateExchangeMessage, StateSemanticType as S,
)
from hesk.ledger.reconciliation import get_unseen_events, reconcile_full_ledger, resolve_exclusive_ownership

T = [1000.0]


@pytest.fixture(autouse=True)
def fixed_clock():
    T[0] = 1000.0
    with mock.patch.object(L, "local_wall_time", lambda: T[0]):
        yield


def send(a, b):
    b.process_message(StateExchangeMessage(a.node_id, a.lamport_clock, dict(a.version_vector), list(a.entries.values())))


def claim(node, prog, qual, wall):
    v = {"assignee": node, "progress": prog, "match_quality": qual}
    return LedgerEntry("t", v, S.EXCLUSIVE_OWNERSHIP, node, 1, wall, 1.0, Provenance(node, ObservationType.DIRECT, 1))


def winner(x, y):
    return resolve_exclusive_ownership(Conflict("t", x, y, S.EXCLUSIVE_OWNERSHIP)).winning_value["assignee"]


@pytest.mark.xfail(strict=True, reason="F1: epsilon-cascade is intransitive (A>B, B>C, C>A)")
def test_F1_ownership_resolution_is_order_independent():
    a, b, c = claim("A", 0.00, 0.9, 10), claim("B", 0.04, 0.5, 11), claim("C", 0.08, 0.1, 12)
    assert len({winner(a, b), winner(b, c), winner(a, c)}) < 3


@pytest.mark.xfail(strict=True, reason="F2: updates within DRIFT_MAX+WALL_THRESHOLD (5s) are treated as concurrent and dropped")
def test_F2_causal_handoff_within_five_seconds_is_applied():
    A, B = LocalStateLedger("A"), LocalStateLedger("B")
    A.write_local("task", "A", S.EXCLUSIVE_OWNERSHIP)
    send(A, B)
    T[0] += 1.0
    B.write_local("task", "B", S.EXCLUSIVE_OWNERSHIP)
    send(B, A)
    assert A.read("task")[0] == "B"


@pytest.mark.xfail(strict=True, reason="F3: entries are stamped with the receiver's Lamport clock, then compared with origin clocks")
def test_F3_causal_handoff_is_not_rejected_by_a_busy_receiver():
    P, X, Y = LocalStateLedger("P"), LocalStateLedger("X"), LocalStateLedger("Y")
    for i in range(40):
        Y.write_local(f"telemetry{i}", i, S.RESOURCE)
    P.write_local("task", "P", S.EXCLUSIVE_OWNERSHIP)
    send(P, X), send(P, Y)
    T[0] += 30.0
    X.write_local("task", "X", S.EXCLUSIVE_OWNERSHIP)
    send(X, Y)
    assert Y.read("task")[0] == "X"


@pytest.mark.xfail(strict=True, reason="F4: COUNTER merges with max, so concurrent increments are lost")
def test_F4_concurrent_counter_increments_are_summed():
    A, B = LocalStateLedger("A"), LocalStateLedger("B")
    A.write_local("c", 0, S.COUNTER), send(A, B)
    A.write_local("c", 1, S.COUNTER)
    B.write_local("c", 1, S.COUNTER)
    send(A, B), send(B, A)
    assert A.read("c")[0] == B.read("c")[0] == 2


@pytest.mark.xfail(strict=True, reason="F5: OBSERVATIONAL merge appends on every receive (not idempotent)")
def test_F5_redelivering_an_observation_is_idempotent():
    A, B = LocalStateLedger("A"), LocalStateLedger("B")
    A.write_local("o", 7, S.OBSERVATIONAL)
    for _ in range(3):
        send(A, B)
    v = B.read("o")[0]
    assert (len(v) if isinstance(v, list) else 1) == 1


@pytest.mark.xfail(strict=True, reason="F6: RESOURCE guard band is not transitive; replicas keep different values forever")
def test_F6_resource_replicas_converge_after_full_exchange():
    ws = {"x": 1000.0, "y": 1001.5, "z": 1003.0}
    R = {n: LocalStateLedger(n) for n in "xyz"}
    for n, ledger in R.items():
        T[0] = ws[n]
        ledger.write_local("r", n, S.RESOURCE)
    T[0] = 1010.0
    # R1 sees x then z; R2 sees y then z; then everyone exchanges everything repeatedly
    r1, r2 = LocalStateLedger("r1"), LocalStateLedger("r2")
    for src, dst in (("x", r1), ("y", r2), ("z", r1), ("z", r2)):
        send(R[src], dst)
    for _ in range(3):
        send(r1, r2), send(r2, r1)
    assert r1.read("r")[0] == r2.read("r")[0]


@pytest.mark.xfail(strict=True, reason="F7: concurrent ownership conflicts are flagged but never resolved outside a reconnection event")
def test_F7_concurrent_claims_in_one_connected_component_converge():
    A, B = LocalStateLedger("A"), LocalStateLedger("B")
    A.write_local("t", "A", S.EXCLUSIVE_OWNERSHIP)
    T[0] += 0.5
    B.write_local("t", "B", S.EXCLUSIVE_OWNERSHIP)
    for _ in range(5):
        send(A, B), send(B, A)
    assert A.read("t")[0] == B.read("t")[0]


@pytest.mark.xfail(strict=True, reason="F8: received events are logged with origin_seq=0 and the version vector is never advanced")
def test_F8_event_log_relays_events_learned_from_a_third_node():
    A, B, C = LocalStateLedger("A"), LocalStateLedger("B"), LocalStateLedger("C")
    A.write_local("k", {"a"}, S.SET_LIKE)
    send(A, B)
    assert get_unseen_events(B.event_log, C.version_vector)


@pytest.mark.xfail(strict=True, reason="F9: progress-first reconciliation has no notion of causality and reverts deliberate handoffs")
def test_F9_reconciliation_keeps_a_causally_later_handoff_with_lower_progress():
    A, B = LocalStateLedger("A"), LocalStateLedger("B")
    A.write_local("t", {"assignee": "A", "progress": 0.6, "match_quality": 0.8}, S.EXCLUSIVE_OWNERSHIP)
    send(A, B)                                  # B learns that A owns the task at 60% progress
    T[0] += 30.0
    B.write_local("t", {"assignee": "B", "progress": 0.1, "match_quality": 0.8}, S.EXCLUSIVE_OWNERSHIP)  # deliberate takeover
    reconcile_full_ledger(A, "B", dict(B.entries))
    assert A.read("t")[0]["assignee"] == "B"
