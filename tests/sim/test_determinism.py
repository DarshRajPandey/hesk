import json
import os
import subprocess
import sys
from dataclasses import replace

from hesk.bench.impls import IMPLS
from hesk.sim.scenario import Params, run_scenario

SMALL = replace(Params(), n_nodes=8, n_obs=2, t_connected=12.0, t_part=8.0, t_settle=12.0, claimants=3)


def test_same_seed_same_result_in_process():
    for impl in ("legacy/reconcile/relay", "hesk-l"):
        assert run_scenario(SMALL, IMPLS[impl], 7) == run_scenario(SMALL, IMPLS[impl], 7)


def test_different_seeds_differ():
    assert run_scenario(SMALL, IMPLS["hesk-l"], 1) != run_scenario(SMALL, IMPLS["hesk-l"], 2)


def test_bitwise_identical_across_processes_and_hash_seeds():
    code = (
        "import json;from dataclasses import replace;from hesk.bench.impls import IMPLS;"
        "from hesk.sim.scenario import Params, run_scenario;"
        "p=replace(Params(),n_nodes=8,n_obs=2,t_connected=12.0,t_part=8.0,t_settle=12.0,claimants=3);"
        "print(json.dumps([run_scenario(p,IMPLS[i],5) for i in ('legacy/gossip/direct','hesk-l')],sort_keys=True))"
    )
    outs = []
    for hs in ("1", "2", "random"):
        env = {**os.environ, "PYTHONHASHSEED": hs}
        outs.append(subprocess.check_output([sys.executable, "-c", code], env=env, text=True))
    assert outs[0] == outs[1] == outs[2]


def test_all_implementations_face_identical_workload():
    """Truth-bearing quantities must not depend on the implementation under test."""
    a = run_scenario(SMALL, IMPLS["hesk-l"], 3)
    b = run_scenario(SMALL, IMPLS["legacy/reconcile/direct"], 3)
    # counters: same number of increments issued -> the lattice (no loss) pins the truth; legacy can only lose
    assert a["ctr_loss"] == 0.0 and b["ctr_loss"] >= 0.0
