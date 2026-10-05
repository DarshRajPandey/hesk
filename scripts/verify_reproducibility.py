"""Re-run a random sample of recorded runs and check they reproduce bit-exactly.

  python scripts/verify_reproducibility.py results/raw/*.jsonl.gz --n 24

A mismatch means the code changed behaviour since the record was produced
(each record carries the git revision that produced it in its "git" field).
"""
import argparse
import gzip
import json
import random
from concurrent.futures import ProcessPoolExecutor

from hesk_sim.runner import run_one


def _open(path):
    return gzip.open(path, "rt") if path.endswith(".gz") else open(path)


def _rerun(r):
    return r, run_one(r["scenario"], r["algo"], r["seed"], r["agent"])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("files", nargs="+")
    ap.add_argument("--n", type=int, default=24)
    ap.add_argument("--seed", type=int, default=0)
    args = ap.parse_args()
    rows = [json.loads(l) for f in args.files for l in _open(f)]
    random.Random(args.seed).shuffle(rows)
    sample = rows[:args.n]
    bad = 0
    with ProcessPoolExecutor() as ex:
        for r, m in ex.map(_rerun, sample):
            same = m["utility_ratio"] == r["utility_ratio"] and m["messages"] == r["messages"]
            bad += not same
            tag = "ok      " if same else "MISMATCH"
            print(f"{tag} {r['suite']:10s} {r['cell']:28s} {r['algo']:16s} rep={r['rep']:<3d} "
                  f"recorded={r['utility_ratio']:.6f} rerun={m['utility_ratio']:.6f} (git {r.get('git')})")
    print(f"\n{len(sample) - bad}/{len(sample)} runs reproduce bit-exactly")
    raise SystemExit(1 if bad else 0)


if __name__ == "__main__":
    main()
