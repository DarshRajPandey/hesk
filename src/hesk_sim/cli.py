"""Command line: run experiment suites, replay single runs.

  python -m hesk_sim.cli list
  python -m hesk_sim.cli run baseline --workers 8           # → runs/baseline.jsonl (resumable)
  python -m hesk_sim.cli run all --reps 3                   # quick smoke of every suite
  python -m hesk_sim.cli one --algo hesk2 --seed 7 --set loss=0.4 kill_frac=0.3
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from concurrent.futures import ProcessPoolExecutor, as_completed

from hesk_sim.runner import run_one, seed_for
from hesk_sim.suites import SUITES, suite_jobs


def git_rev() -> str:
    try:
        return subprocess.check_output(["git", "rev-parse", "--short", "HEAD"], stderr=subprocess.DEVNULL,
                                       cwd=os.path.dirname(__file__)).decode().strip()
    except Exception:
        return "unknown"


def _key(suite, cell, algo, rep):
    return f"{suite}|{cell}|{algo}|{rep}"


def _work(job):
    suite, cell, scen, algo, agent, rep = job
    seed = seed_for(suite, cell, rep)
    m = run_one(scen, algo, seed, agent)
    return {"suite": suite, "cell": cell, "algo": algo, "rep": rep, "seed": seed,
            "scenario": scen, "agent": agent, **m}


def cmd_run(args) -> None:
    names = SUITES if args.suite == "all" else args.suite.split(",")
    os.makedirs(args.out, exist_ok=True)
    rev = git_rev()
    for name in names:
        path = os.path.join(args.out, f"{name}.jsonl")
        done = set()
        if os.path.exists(path):
            with open(path) as fh:
                for line in fh:
                    r = json.loads(line)
                    done.add(_key(r["suite"], r["cell"], r["algo"], r["rep"]))
        jobs = [j for j in suite_jobs(name, args.reps) if _key(j[0], j[1], j[3], j[5]) not in done]
        print(f"[{name}] {len(jobs)} runs to do ({len(done)} already in {path})", flush=True)
        t0 = time.time()
        with open(path, "a") as fh, ProcessPoolExecutor(args.workers) as ex:
            futs = [ex.submit(_work, j) for j in jobs]
            for i, f in enumerate(as_completed(futs), 1):
                rec = f.result()
                rec["git"] = rev
                fh.write(json.dumps(rec) + "\n")
                fh.flush()
                if i % 50 == 0 or i == len(jobs):
                    el = time.time() - t0
                    print(f"  {i}/{len(jobs)}  {el:6.0f}s elapsed  ~{el / i * (len(jobs) - i):6.0f}s left", flush=True)


def cmd_one(args) -> None:
    scen = {}
    for kv in args.set or []:
        k, v = kv.split("=", 1)
        scen[k] = json.loads(v)
    agent = {}
    for kv in args.agent or []:
        k, v = kv.split("=", 1)
        agent[k] = json.loads(v)
    r = run_one(scen, args.algo, args.seed, agent, keep_timeline=True)
    print(json.dumps(r, indent=1))


def cmd_list(_args) -> None:
    for s in SUITES:
        jobs = suite_jobs(s)
        cells = sorted({j[1] for j in jobs})
        algos = sorted({j[3] for j in jobs})
        print(f"{s:10s} {len(jobs):5d} runs  {len(cells):3d} cells  algos={','.join(algos)}")
    print(f"{'TOTAL':10s} {sum(len(suite_jobs(s)) for s in SUITES):5d} runs")


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(prog="hesk_sim")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run")
    r.add_argument("suite", help="suite name, comma list, or 'all'")
    r.add_argument("--reps", type=int, default=None, help="override repetitions per cell")
    r.add_argument("--workers", type=int, default=os.cpu_count())
    r.add_argument("--out", default="runs")
    r.set_defaults(fn=cmd_run)
    o = sub.add_parser("one")
    o.add_argument("--algo", default="hesk2")
    o.add_argument("--seed", type=int, default=0)
    o.add_argument("--set", nargs="*", help="scenario overrides key=json")
    o.add_argument("--agent", nargs="*", help="agent overrides key=json (e.g. fd_k=6)")
    o.set_defaults(fn=cmd_one)
    l = sub.add_parser("list")
    l.set_defaults(fn=cmd_list)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main(sys.argv[1:])
