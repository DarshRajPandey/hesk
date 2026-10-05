"""Parallel experiment runner.

    python -m hesk.bench run E1_audit --seeds 100 --jobs 4 --out results

Writes ``results/raw/<exp>.jsonl.gz`` (one row per run: cell labels, implementation, seed,
metrics) and ``results/manifest.json`` (code version, environment, exact command).
"""
from __future__ import annotations

import argparse
import gzip
import json
import multiprocessing as mp
import os
import platform
import subprocess
import sys
import time
from dataclasses import asdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from hesk.bench import algebra
from hesk.bench.experiments import DEFAULT_SEEDS, EXPERIMENTS, SEEDS, Cell, build
from hesk.bench import allocation, legacy_patches
from hesk.bench.impls import resolve
from hesk.sim.scenario import Params, run_scenario

Job = Tuple[str, Tuple[Tuple[str, object], ...], Dict[str, Any], str, int]


def _work(job: Job) -> Dict[str, Any]:
    exp, labels, params, impl, seed = job
    t0 = time.perf_counter()
    factory, patches = resolve(impl)
    with legacy_patches.apply(patches):
        res = run_scenario(Params(**params), factory, seed)
    row: Dict[str, Any] = {"exp": exp, **dict(labels), "impl": impl, "seed": seed, **res}
    row["wall_s"] = round(time.perf_counter() - t0, 4)
    return row


def _work_alloc(job) -> Dict[str, Any]:
    labels, policy, seed = job
    return {"exp": "E11_alloc", **labels, "impl": policy, "seed": seed, **allocation.trial(labels, policy, seed)}


def jobs_for(exp: str, seeds: int) -> List[Job]:
    jobs: List[Job] = []
    for cell in build(exp):
        for impl in cell.impls:
            for seed in range(seeds):
                jobs.append((exp, cell.labels, asdict(cell.params), impl, seed))
    return jobs


def run_experiment(exp: str, seeds: int, n_jobs: int, out: Path) -> Path:
    path = out / "raw" / f"{exp}.jsonl.gz"
    path.parent.mkdir(parents=True, exist_ok=True)
    if exp == "E9_algebra":
        rows = []
        for k in (2, 3, 4, 5, 6):
            for spread in (0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.4):
                for seed in range(seeds * 10):
                    rows.append({"exp": exp, "k": k, "spread": spread, "seed": seed, **algebra.trial(k, spread, seed)})
    elif exp == "E11_alloc":
        jobs = [(lab, pol, seed) for lab, pol in allocation.grid() for seed in range(seeds)]
        with mp.Pool(n_jobs) as pool:
            rows = list(pool.imap_unordered(_work_alloc, jobs, chunksize=32))
        rows.sort(key=lambda r: (json.dumps({k: v for k, v in r.items() if k not in ("seed", "utility_ratio", "served_frac", "rare_served_frac", "oracle_utility")}, default=str), r["seed"]))
    else:
        jobs = jobs_for(exp, seeds)
        with mp.Pool(n_jobs) as pool:
            rows = list(pool.imap_unordered(_work, jobs, chunksize=8))
        rows.sort(key=lambda r: (json.dumps({k: v for k, v in r.items() if k not in ("seed", "wall_s")}, default=str), r["seed"]))
    with gzip.open(path, "wt", compresslevel=9) as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    return path


def _git(*args: str) -> str:
    try:
        return subprocess.check_output(["git", *args], text=True, stderr=subprocess.DEVNULL).strip()
    except Exception:
        return "unknown"


def write_manifest(out: Path, experiments: List[str], seeds: Dict[str, int], wall_s: float) -> None:
    import numpy
    manifest = {
        "git_commit": _git("rev-parse", "HEAD"),
        "git_dirty": bool(_git("status", "--porcelain")),
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "numpy": numpy.__version__,
        "command": " ".join(sys.argv),
        "experiments": experiments,
        "seeds": seeds,
        "wall_seconds": round(wall_s, 1),
        "pythonhashseed": os.environ.get("PYTHONHASHSEED", "unset"),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


def main(argv: List[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="hesk.bench run")
    ap.add_argument("experiments", nargs="+", help=f"any of {', '.join(EXPERIMENTS)}, E9_algebra, E11_alloc, or 'all'")
    ap.add_argument("--seeds", type=int, default=None, help="override seeds per cell")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 1)
    ap.add_argument("--out", type=Path, default=Path("results"))
    a = ap.parse_args(argv)
    exps = list(EXPERIMENTS) + ["E9_algebra", "E11_alloc"] if a.experiments == ["all"] else a.experiments
    used: Dict[str, int] = {}
    t0 = time.time()
    for e in exps:
        n = a.seeds if a.seeds is not None else SEEDS.get(e, DEFAULT_SEEDS)
        used[e] = n
        t = time.time()
        path = run_experiment(e, n, a.jobs, a.out)
        print(f"{e:16s} seeds={n:<4d} -> {path} ({time.time() - t:.0f}s)", flush=True)
    write_manifest(a.out, exps, used, time.time() - t0)


if __name__ == "__main__":
    main()
