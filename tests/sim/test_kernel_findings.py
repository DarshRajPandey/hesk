"""Kernel-level findings, encoded as tests so they cannot silently regress or be forgotten.

A strict xfail documents a *known* defect: the test passes the day someone fixes it,
and pytest then reports XPASS(strict) → forces the marker to be removed.
"""
import copy

import pytest

import hesk.ledger.ledger as ledger_mod
from hesk.ledger.ledger import LocalStateLedger
from hesk.ledger.model import StateSemanticType
from hesk.ledger.reconciliation import reconcile_full_ledger


def _pair(semantic, va, vb, ta, tb, monkeypatch):
    a, b = LocalStateLedger("A"), LocalStateLedger("B")
    monkeypatch.setattr(ledger_mod, "local_wall_time", lambda: ta)
    a.write_local("k", va, semantic)
    monkeypatch.setattr(ledger_mod, "local_wall_time", lambda: tb)
    b.write_local("k", vb, semantic)
    ea, eb = copy.deepcopy(a.entries), copy.deepcopy(b.entries)
    reconcile_full_ledger(a, "B", eb)
    reconcile_full_ledger(b, "A", ea)
    return a.entries["k"].value, b.entries["k"].value


@pytest.mark.xfail(strict=True, reason="Finding K1: RESOURCE/MISSION_POLICY tie-breaks favour the local "
                                       "replica, so two replicas that reconcile with each other keep different values")
@pytest.mark.parametrize("semantic", [StateSemanticType.RESOURCE, StateSemanticType.MISSION_POLICY])
def test_reconciliation_converges_within_drift_window(semantic, monkeypatch):
    va, vb = _pair(semantic, 10, 20, 100.0, 101.0, monkeypatch)
    assert va == vb


def test_ownership_reconciliation_converges(monkeypatch):
    own = StateSemanticType.EXCLUSIVE_OWNERSHIP
    va, vb = _pair(own, {"assignee": "A", "progress": 0.1, "match_quality": 0.5},
                   {"assignee": "B", "progress": 0.1, "match_quality": 0.5}, 100.0, 101.0, monkeypatch)
    assert va == vb


def test_progress_first_rule_resurrects_stale_owner(monkeypatch):
    """Finding K2: Alg 008 has no causal order. A reassignment made *after* the old
    owner died (progress 0) loses to the dead owner's stale record (progress > 0)."""
    own = StateSemanticType.EXCLUSIVE_OWNERSHIP
    dead = {"assignee": "dead_node", "progress": 0.6, "match_quality": 0.9}
    fresh = {"assignee": "successor", "progress": 0.0, "match_quality": 0.9}
    va, vb = _pair(own, dead, fresh, 100.0, 400.0, monkeypatch)
    assert va == vb == dead
