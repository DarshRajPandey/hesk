"""HESK-L must converge and lose nothing on the default scenario, for every seed we try."""
from dataclasses import replace

import pytest

from hesk.bench.impls import IMPLS
from hesk.sim.scenario import Params, run_scenario

P = replace(Params(), claimants=3)


@pytest.mark.parametrize("seed", range(12))
def test_hesk_l_converges_and_preserves_every_update(seed):
    r = run_scenario(P, IMPLS["hesk-l"], seed)
    assert r["conv_all"] == 1
    assert r["chain_stale"] == 0.0 and r["chain_split"] == 0.0
    assert r["contest_split"] == 0.0
    assert r["ctr_loss"] == 0.0
    assert r["obs_dup"] == 0.0 and r["aborted"] == 0
    assert r["conv_res"] == 1  # replicas agree; *which* report is newest is limited by clock skew (see below)


@pytest.mark.parametrize("seed", range(12))
def test_hesk_l_resource_is_exactly_fresh_when_clocks_agree(seed):
    r = run_scenario(replace(P, clock_skew=0.0), IMPLS["hesk-l"], seed)
    assert r["conv_res"] == 1 and r["res_stale"] == 0.0


@pytest.mark.parametrize("resolver", ["hesk-l", "hesk-l/exact", "hesk-l/eps-resolver"])
def test_every_hesk_l_resolver_converges_even_under_harsh_network(resolver):
    harsh = replace(P, n_groups=4, claimants=4, loss=0.2, one_per_group=False)
    for seed in range(8):
        assert run_scenario(harsh, IMPLS[resolver], seed)["conv_own"] == 1
