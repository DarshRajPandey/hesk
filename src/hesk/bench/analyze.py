"""Aggregate raw runs into tables (results/REPORT.md, summary.csv) and figures (results/figures).

    python -m hesk.bench report --out results
"""
from __future__ import annotations

import argparse
import csv
import glob
import gzip
import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

BINARY = {"conv_all", "conv_own", "conv_ctr", "conv_obs", "conv_res", "aborted",
          "legacy_order_dependent", "exact_order_dependent", "bucketed_order_dependent", "has_cycle"}
METRICS = ["conv_all", "conv_own", "conv_ctr", "conv_obs", "conv_res", "chain_stale", "chain_split", "contest_split",
           "contest_regret", "ctr_loss", "obs_dup", "obs_recall", "res_stale", "res_stale2", "res_lag_s", "aborted", "t_conv_own", "t_conv_res",
           "bytes", "t_conv_ctr", "t_conv_obs", "legacy_order_dependent", "legacy_n_winners", "exact_order_dependent", "bucketed_order_dependent",
           "has_cycle", "regret_legacy_first_order", "regret_exact", "regret_bucketed", "utility_ratio", "served_frac",
           "rare_served_frac", "own_accept", "contest_orphan", "contest_dup"]
NOT_LABEL = {"exp", "impl", "seed", "wall_s", "delivered", "max_units", "oracle_utility", "live_nodes", *METRICS}


def load(out: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for p in sorted(glob.glob(str(out / "raw" / "*.jsonl.gz"))):
        with gzip.open(p, "rt") as f:
            rows += [json.loads(l) for l in f]
    return rows


def wilson(k: float, n: int, z: float = 1.96) -> Tuple[float, float]:
    if n == 0:
        return (math.nan, math.nan)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def stat(values: Sequence[Optional[float]], binary: bool) -> Tuple[float, float, float, int]:
    v = np.array([x for x in values if x is not None], dtype=float)
    if len(v) == 0:
        return (math.nan, math.nan, math.nan, 0)
    if binary:
        lo, hi = wilson(v.sum(), len(v))
        return (float(v.mean()), lo, hi, len(v))
    rng = np.random.default_rng(0)
    boots = rng.choice(v, size=(2000, len(v))).mean(axis=1)
    return (float(v.mean()), float(np.percentile(boots, 2.5)), float(np.percentile(boots, 97.5)), len(v))


def group(rows: List[Dict[str, Any]], exp: str) -> Dict[Tuple, List[Dict[str, Any]]]:
    g: Dict[Tuple, List[Dict[str, Any]]] = defaultdict(list)
    for r in rows:
        if r["exp"] != exp:
            continue
        labels = tuple((k, r[k]) for k in sorted(r) if k not in NOT_LABEL)
        g[labels + (("impl", r.get("impl", "")),)].append(r)
    return g


def agg(rows, exp, metric) -> Dict[Tuple, Tuple[float, float, float, int]]:
    return {k: stat([r.get(metric) for r in v], metric in BINARY) for k, v in group(rows, exp).items()}


def fmt(s: Tuple[float, float, float, int], pct: bool) -> str:
    m, lo, hi, n = s
    if n == 0:
        return "–"
    f = (lambda x: f"{100 * x:.0f}%") if pct else (lambda x: f"{x:.3g}")
    return f"{f(m)} [{f(lo)}, {f(hi)}]"


def table(rows, exp, title) -> str:
    g = group(rows, exp)
    cols = [m for m in METRICS if any(r.get(m) is not None for v in g.values() for r in v)]
    pct = {"conv_all", "conv_own", "conv_ctr", "conv_obs", "conv_res", "chain_stale", "chain_split", "contest_split",
           "ctr_loss", "obs_dup", "obs_recall", "res_stale", "res_stale2", "aborted", "utility_ratio", "served_frac",
           "rare_served_frac", "own_accept", "contest_orphan", *BINARY}
    head = ["cell", "implementation", "n"] + cols
    lines = [f"### {title}", "", "| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for key in sorted(g, key=lambda k: (str([x for x in k if x[0] != "impl"]), k[-1][1])):
        cell = ", ".join(f"{a}={b}" for a, b in key[:-1]) or "default"
        vals = [fmt(stat([r.get(m) for r in g[key]], m in BINARY), m in pct) for m in cols]
        lines.append("| " + " | ".join([cell, key[-1][1], str(len(g[key]))] + vals) + " |")
    return "\n".join(lines) + "\n"


# ─── figures ──────────────────────────────────────────────────────────────────

COLOR = {"hesk-l": "#2a78d6", "legacy/reconcile/direct": "#eb6834", "legacy/reconcile/relay": "#1baf7a",
         "legacy/gossip/relay": "#e87ba4", "legacy/gossip/direct": "#4a3aa7", "hesk-l/exact": "#eda100",
         "hesk-l/eps-resolver": "#e34948", "tightest-fit": "#eb6834", "random": "#1baf7a", "hesk(w=0)": "#e87ba4",
         "hesk(w=2)": "#2a78d6", "hesk(w=16)": "#4a3aa7", "baseline/quorum": "#1baf7a", "baseline/lww-gossip": "#4a3aa7"}
MARK = {"hesk-l": "o", "legacy/reconcile/direct": "s", "legacy/reconcile/relay": "^", "legacy/gossip/relay": "D",
        "legacy/gossip/direct": "v", "hesk-l/exact": "P", "hesk-l/eps-resolver": "X", "tightest-fit": "s", "random": "^", "hesk(w=0)": "D", "hesk(w=2)": "o",
        "hesk(w=16)": "v", "baseline/quorum": "^", "baseline/lww-gossip": "D"}


def _plt():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False, "axes.spines.right": False, "axes.grid": True,
                         "grid.color": "#e6e5e0", "grid.linewidth": 0.6, "axes.edgecolor": "#8a8984",
                         "axes.labelcolor": "#52514e", "xtick.color": "#52514e", "ytick.color": "#52514e",
                         "figure.facecolor": "#fcfcfb", "axes.facecolor": "#fcfcfb", "legend.frameon": False})
    return plt


def line_fig(rows, exp, xkey, metric, ylabel, xlabel, path, title, impls=None, logx=False, vline=None, pct=True, where=None):
    plt = _plt()
    a = agg(rows, exp, metric)
    series: Dict[str, List[Tuple[float, Tuple]]] = defaultdict(list)
    for key, s in a.items():
        d = dict(key)
        if impls and d["impl"] not in impls:
            continue
        if where and any(d.get(k) != v for k, v in where.items()):
            continue
        series[d["impl"]].append((d[xkey], s))
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    for impl, pts in sorted(series.items(), key=lambda kv: list(COLOR).index(kv[0]) if kv[0] in COLOR else 99):
        pts.sort(key=lambda t: t[0])
        x = [p[0] for p in pts]
        m = np.array([p[1][0] for p in pts]); lo = np.array([p[1][1] for p in pts]); hi = np.array([p[1][2] for p in pts])
        sc = 100 if pct else 1
        ax.errorbar(x, m * sc, yerr=[np.clip(m - lo, 0, None) * sc, np.clip(hi - m, 0, None) * sc], color=COLOR.get(impl, "#888"), marker=MARK.get(impl, "o"),
                    ms=6, lw=2, capsize=3, mec="#fcfcfb", mew=1.2, label=impl)
    if vline:
        ax.axvline(vline[0], color="#8a8984", ls="--", lw=1)
        ax.text(vline[0], ax.get_ylim()[1] * 0.97, " " + vline[1], va="top", color="#52514e", fontsize=9)
    if logx:
        ax.set_xscale("symlog", linthresh=0.01)
    ax.set_xlabel(xlabel); ax.set_ylabel(ylabel); ax.set_title(title, loc="left", fontsize=11, color="#0b0b0b")
    ax.legend(fontsize=8.5, loc="best")
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def fig_audit(rows, path):
    plt = _plt()
    items = [("E1_audit", "workload", "main", "contest_split", "contested keys with split owners"),
             ("E1_audit", "workload", "main", "chain_stale", "stale replicas after causal handoff"),
             ("E1_audit", "workload", "main", "ctr_loss", "increments lost"),
             ("E1_audit", "workload", "main", "res_stale", "stale resource reads"),
             ("E1_audit", "workload", "obs", "obs_dup", "duplicated observation entries")]
    impls = ["legacy/gossip/relay", "legacy/reconcile/relay", "legacy/gossip/direct", "legacy/reconcile/direct", "hesk-l"]
    fig, axes = plt.subplots(1, len(items), figsize=(13, 3.6), sharey=True)
    for ax, (exp, lk, lv, metric, title) in zip(axes, items):
        a = agg(rows, exp, metric)
        for i, impl in enumerate(impls):
            s = next((v for k, v in a.items() if dict(k).get("impl") == impl and dict(k).get(lk) == lv), None)
            if s is None or s[3] == 0:
                continue
            ax.bar(i, 100 * s[0], color=COLOR[impl], width=0.7, edgecolor="#fcfcfb", linewidth=2)
            ax.errorbar(i, 100 * s[0], yerr=[[max(0.0, 100 * (s[0] - s[1]))], [max(0.0, 100 * (s[2] - s[0]))]], color="#0b0b0b", lw=1, capsize=2)
        ax.set_title(title, fontsize=9, loc="left"); ax.set_xticks([]); ax.grid(axis="x", visible=False)
    axes[0].set_ylabel("% (95% CI)")
    handles = [plt.Rectangle((0, 0), 1, 1, color=COLOR[i]) for i in impls]
    fig.legend(handles, impls, ncol=5, loc="lower center", fontsize=9)
    fig.tight_layout(rect=(0, 0.08, 1, 1)); fig.savefig(path, dpi=160); plt.close(fig)


def fig_algebra(rows, path):
    plt = _plt()
    fig, ax = plt.subplots(figsize=(7.2, 4.2))
    g: Dict[Tuple, List[float]] = defaultdict(list)
    for r in rows:
        if r["exp"] == "E9_algebra":
            g[(r["k"], r["spread"])].append(r["legacy_order_dependent"])
    ks = sorted({k for k, _ in g})
    cols = ["#2a78d6", "#eb6834", "#1baf7a", "#e87ba4", "#4a3aa7"]
    for c, k, mk in zip(cols, ks, "osD^v"):
        xs = sorted(s for kk, s in g if kk == k)
        ys = [100 * np.mean(g[(k, s)]) for s in xs]
        ax.plot(xs, ys, color=c, marker=mk, lw=2, ms=6, mec="#fcfcfb", label=f"{k} concurrent claims")
    ax.set_xscale("symlog", linthresh=0.01)
    ax.set_xlabel("spread of claimants' progress (std-dev; legacy ε = 0.05)")
    ax.set_ylabel("% of claim sets where winner depends on merge order")
    ax.set_title("Legacy ε-cascade is not a valid merge: total-order policies are 0% everywhere", loc="left", fontsize=10.5)
    ax.legend(fontsize=8.5); fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def fig_scale(rows, path):
    plt = _plt()
    fig, axes = plt.subplots(1, 2, figsize=(10, 3.8))
    for ax, metric, yl in ((axes[0], "t_conv_own", "seconds after heal until all replicas agree"), (axes[1], "bytes", "mean replica state (bytes)")):
        a = agg(rows, "E6_scale", metric)
        for impl in ("hesk-l", "legacy/reconcile/direct"):
            pts = sorted((dict(k)["nodes"], s) for k, s in a.items() if dict(k)["impl"] == impl and s[3])
            if not pts:
                continue
            x = [p[0] for p in pts]; m = np.array([p[1][0] for p in pts]); lo = np.array([p[1][1] for p in pts]); hi = np.array([p[1][2] for p in pts])
            ax.errorbar(x, m, yerr=[np.clip(m - lo, 0, None), np.clip(hi - m, 0, None)], color=COLOR[impl], marker=MARK[impl], lw=2, ms=6, capsize=3, mec="#fcfcfb", label=impl)
        ax.set_xlabel("nodes"); ax.set_ylabel(yl); ax.legend(fontsize=8.5)
    axes[0].set_title("time to convergence (runs that converged)", loc="left", fontsize=10)
    axes[1].set_title("cost of the fix: replica state size", loc="left", fontsize=10)
    fig.tight_layout(); fig.savefig(path, dpi=160); plt.close(fig)


def fig_failure(rows, path):
    """2 x 4 panel: rows = metrics, columns = adversarial sweeps."""
    plt = _plt()
    sweeps = [("loss", "packet loss"), ("crash", "fraction of nodes killed"), ("latency", "one-way latency (s)"),
              ("partition_s", "partition length (s)")]
    metrics = [("conv_all", "% runs where all live replicas agree", True),
               ("contest_orphan", "% reassigned tasks nobody could take", True),
               ("contest_dup", "extra concurrent executors per task", False),
               ("ctr_loss", "% counter increments lost", True)]
    impls = ("hesk-l", "baseline/lww-gossip", "baseline/quorum", "legacy/reconcile/direct")
    fig, axes = plt.subplots(len(metrics), len(sweeps), figsize=(15, 11), sharey="row")
    for ci, (sw, xl) in enumerate(sweeps):
        for ri, (m, yl, pct) in enumerate(metrics):
            ax = axes[ri][ci]
            a = agg(rows, "E13_failure", m)
            for impl in impls:
                pts = sorted((dict(k)["x"], v) for k, v in a.items() if dict(k)["impl"] == impl and dict(k)["sweep"] == sw and v[3])
                if not pts:
                    continue
                sc = 100 if pct else 1
                x = [p_[0] for p_ in pts]; mm = np.array([p_[1][0] for p_ in pts]) * sc
                lo = np.array([p_[1][1] for p_ in pts]) * sc; hi = np.array([p_[1][2] for p_ in pts]) * sc
                ax.errorbar(x, mm, yerr=[np.clip(mm - lo, 0, None), np.clip(hi - mm, 0, None)], color=COLOR[impl], marker=MARK[impl], ms=5, lw=1.8, capsize=2,
                            mec="#fcfcfb", label=impl)
            if ri == len(metrics) - 1:
                ax.set_xlabel(xl)
            if ci == 0:
                ax.set_ylabel(yl, fontsize=9)
    axes[0][0].legend(fontsize=8)
    fig.suptitle("Adversarial sweeps (E13): 95% CIs over 60 seeds per point", x=0.01, ha="left", fontsize=12)
    fig.tight_layout(); fig.savefig(path, dpi=150); plt.close(fig)


def report(out: Path) -> None:
    rows = load(out)
    figs = out / "figures"; figs.mkdir(exist_ok=True, parents=True)
    own = ("legacy/reconcile/relay", "legacy/reconcile/direct", "hesk-l", "hesk-l/exact", "hesk-l/eps-resolver")
    line_fig(rows, "E2_groups", "groups", "contest_split", "% contested keys where replicas disagree on the owner", "partition groups = concurrent claimants",
             figs / "e2_groups_split.png", "Split-brain after healing vs. number of partitions", own)
    line_fig(rows, "E3_spread", "spread", "contest_split", "% contested keys where replicas disagree on the owner", "std-dev of claimants' progress",
             figs / "e3_spread_split.png", "Split-brain vs. how close the claimants' progress is (4 partitions)", own, logx=True, vline=(0.05, "legacy ε"))
    line_fig(rows, "E4_handoff_gap", "gap", "chain_stale", "% replicas holding a stale owner", "seconds between seeing a claim and taking over",
             figs / "e4_handoff_gap.png", "Causal handoffs are silently dropped inside a 5 s window",
             ("legacy/gossip/relay", "legacy/reconcile/relay", "legacy/gossip/direct", "hesk-l"), vline=(5.0, "5 s window"))
    line_fig(rows, "E5_skew", "skew", "res_stale", "% stale resource reads", "clock skew std-dev (s)", figs / "e5_skew.png",
             "Resource freshness vs. clock skew", ("legacy/reconcile/relay", "legacy/reconcile/direct", "hesk-l", "hesk-l/-lww"), logx=True)
    line_fig(rows, "E8_intra_group", "claimants", "contest_split", "% contested keys where replicas disagree on the owner",
             "concurrent claimants inside one connected component", figs / "e8_intra_group.png",
             "Conflicts are flagged but never resolved outside a reconnection event", own)
    pols = ("random", "tightest-fit", "hesk(w=0)", "hesk(w=2)", "hesk(w=16)")
    line_fig(rows, "E11_alloc", "load", "utility_ratio", "% of offline-optimal utility", "tasks per node (offered load)",
             figs / "e11_alloc_load.png", "Allocation under adversarial arrival order (common tasks first)", pols,
             where={"sweep": "load", "order": "common-first"})
    if any(r["exp"] == "E13_failure" for r in rows):
        fig_failure(rows, figs / "e13_failure.png")
    fig_audit(rows, figs / "e1_audit.png"); fig_algebra(rows, figs / "e9_algebra.png"); fig_scale(rows, figs / "e6_scale.png")

    titles = {"E1_audit": "E1 — Audit: every implementation, default scenario", "E2_groups": "E2 — Partition groups = concurrent claimants",
              "E3_spread": "E3 — Claim-spread sweep", "E4_handoff_gap": "E4 — Causal handoff gap", "E5_skew": "E5 — Clock skew",
              "E6_scale": "E6 — Swarm size", "E7_ablation": "E7 — HESK-L ablation", "E8_intra_group": "E8 — Intra-group concurrent claims",
              "E9_algebra": "E9 — Merge-order dependence of the ownership comparator (pure algebra)",
              "E10_root_cause": "E10 — Root-cause factorial on the legacy ledger",
              "E12_baselines": "E12 — HESK-L vs conventional baselines (quorum consensus, LWW gossip)",
              "E13_failure": "E13 — Adversarial sweeps: packet loss, crashes, latency, partition length",
              "E11_alloc": "E11 — Allocation: HESK scarcity-aware vs baselines (share of offline-optimal utility)"}
    md = ["# Results (auto-generated by `python -m hesk.bench report`)", "",
          "Rates are shown as mean [95% CI]: Wilson interval for 0/1 outcomes, bootstrap (2000 resamples) otherwise.", ""]
    for e, t in titles.items():
        if any(r["exp"] == e for r in rows):
            md.append(table(rows, e, t))
    (out / "REPORT.md").write_text("\n".join(md))
    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(["exp", "cell", "impl", "metric", "n", "mean", "ci_lo", "ci_hi"])
        for e in titles:
            for m in METRICS:
                for k, s in agg(rows, e, m).items():
                    if s[3]:
                        w.writerow([e, ";".join(f"{a}={b}" for a, b in k[:-1]), k[-1][1], m, s[3], f"{s[0]:.6g}", f"{s[1]:.6g}", f"{s[2]:.6g}"])


def main(argv: Optional[List[str]] = None) -> None:
    ap = argparse.ArgumentParser(prog="hesk.bench report")
    ap.add_argument("--out", type=Path, default=Path("results"))
    report(ap.parse_args(argv).out)
    print("wrote REPORT.md, summary.csv, figures/")


if __name__ == "__main__":
    main()
