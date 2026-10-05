"""Tests for the research harness itself: if these fail, no figure can be trusted."""
import copy
import random

import pytest

from hesk_sim.engine import EventLoop
from hesk_sim.network import Message, Network
from hesk_sim.runner import ALGORITHMS, run_one, seed_for
from hesk_sim.scenario import ScenarioConfig, generate
from hesk_sim.world import World

SHORT = {"duration": 200.0}


def _strip(r):
    return {k: v for k, v in r.items() if k != "wall_s"}


@pytest.mark.parametrize("algo", ["hesk3", "cbba", "central"])
def test_run_is_deterministic(algo):
    scen = dict(SHORT, loss=0.3, kill_frac=0.2, kill_window=[50.0, 150.0])
    assert _strip(run_one(scen, algo, 42)) == _strip(run_one(scen, algo, 42))


def test_seed_does_not_depend_on_algorithm():
    assert seed_for("s", "c", 3) == seed_for("s", "c", 3)
    assert seed_for("s", "c", 3) != seed_for("s", "c", 4)


def test_layout_independent_of_fault_config():
    """Common random numbers: adding faults must not reshuffle fleet or mission."""
    a, b = World(ScenarioConfig(), 7), World(ScenarioConfig(loss=0.5, kill_frac=0.3), 7)
    assert [(n.node_id, n.archetype, n.caps) for n in a.node_specs] == [(n.node_id, n.archetype, n.caps) for n in b.node_specs]
    assert [(t.id, t.pos, t.arrival) for t in a.tasks] == [(t.id, t.pos, t.arrival) for t in b.tasks]


def test_fleet_composition():
    nodes, tasks = generate(ScenarioConfig(), random.Random(0))
    kinds = [n.archetype for n in nodes]
    assert len(nodes) == 24 and kinds.count("thermal") == 3 and kinds.count("gpu") == 2
    assert sum(t.template == "sar_thermal" for t in tasks) == 3


def _net(**kw):
    loop = EventLoop()
    net = Network(loop, random.Random(1), **kw)
    got = {"a": 0, "b": 0, "c": 0}
    for n in got:
        net.register(n, lambda m, n=n: got.__setitem__(n, got[n] + 1))
    return loop, net, got


@pytest.mark.parametrize("burst", [1.0, 8.0])
def test_loss_rate_matches_configuration(burst):
    loop, net, got = _net(loss=0.4, burst_len=burst)
    for _ in range(20000):
        net.send(Message("x", "a", {}, dst="b"))
    loop.run_until(1e9)
    assert abs(got["b"] / 20000 - 0.6) < 0.03


def test_partition_isolates_and_heal_restores():
    loop, net, got = _net()
    net.set_partition([["a", "b"], ["c"]])
    net.send(Message("x", "a", {}))
    loop.run_until(10)
    assert got == {"a": 0, "b": 1, "c": 0}
    net.heal()
    net.send(Message("x", "a", {}))
    loop.run_until(20)
    assert got["c"] == 1


def test_dead_nodes_neither_send_nor_receive():
    loop, net, got = _net()
    net.alive["c"] = False
    net.send(Message("x", "a", {}))
    net.send(Message("x", "c", {}))
    loop.run_until(10)
    assert got == {"a": 0, "b": 1, "c": 0}


@pytest.mark.parametrize("algo", sorted(ALGORITHMS))
def test_every_algorithm_completes_a_nominal_mission(algo):
    r = run_one({"duration": 300.0}, algo, 1)
    assert 0.0 <= r["utility_ratio"] <= 1.0
    floor = {"abl-tiers": 0.3, "independent": 0.2}.get(algo, 0.55)  # independent = no-coordination null baseline
    assert r["utility_ratio"] > floor, r


def test_oracle_never_communicates():
    assert run_one(SHORT, "oracle", 3)["messages"] == 0


def test_agents_do_not_import_ground_truth():
    """README invariant: no HESK node may read simulator-global truth."""
    import inspect
    import hesk_sim.agents.hesk_agent as h
    import hesk_sim.agents.cbba as c
    for mod in (h, c):
        src = inspect.getsource(mod)
        assert "World" not in src and "bodies" not in src and "task_by_id" not in src
